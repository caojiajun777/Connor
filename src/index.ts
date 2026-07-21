#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod/v4";
import { formatPost, formatSearchResult, formatSession } from "./format.js";
import { withAuthenticatedPage } from "./services/browser.js";
import {
  getPost,
  profilePosts,
  searchPosts,
  sessionStatus,
  XAuthenticationError
} from "./services/x.js";

const ResponseFormatSchema = z.enum(["markdown", "json"]).default("markdown");
const DateSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "Date must use YYYY-MM-DD")
  .optional();

const PaginationFields = {
  limit: z.number().int().min(1).max(20).default(5).describe("Maximum posts to return (1-20)."),
  offset: z.number().int().min(0).max(100).default(0).describe("Posts to skip for pagination (0-100).")
};

const SearchSchema = z
  .object({
    query: z
      .string()
      .min(2)
      .max(500)
      .describe('X search query. Supports X operators such as from:, filter:, OR, and quoted phrases.'),
    ...PaginationFields,
    since: DateSchema.describe("Optional inclusive lower date bound in YYYY-MM-DD."),
    until: DateSchema.describe("Optional exclusive upper date bound in YYYY-MM-DD."),
    lang: z
      .string()
      .regex(/^[a-z]{2,3}$/i, "Language must be a 2-3 letter code")
      .optional()
      .describe("Optional X language filter, for example en or zh."),
    response_format: ResponseFormatSchema
  })
  .strict();

const ProfileSchema = z
  .object({
    handle: z
      .string()
      .regex(/^@?[A-Za-z0-9_]{1,15}$/, "Invalid X handle")
      .describe("X account handle, with or without @."),
    ...PaginationFields,
    response_format: ResponseFormatSchema
  })
  .strict();

const PostSchema = z
  .object({
    url: z.string().min(1).max(500).describe("Full x.com or twitter.com status URL."),
    response_format: ResponseFormatSchema
  })
  .strict();

const SessionSchema = z
  .object({ response_format: ResponseFormatSchema })
  .strict();

function classifyToolError(error: unknown): {
  reason_code: string;
  reason: string;
  recommended_actions: string[];
  session?: Record<string, unknown>;
} {
  if (error instanceof XAuthenticationError) {
    return {
      reason_code: error.status.reason_code,
      reason: error.status.reason,
      recommended_actions: error.status.recommended_actions,
      session: { ...error.status }
    };
  }
  const message = error instanceof Error ? error.message : String(error);
  if (/profile.*(open|in use)|SingletonLock|ProcessSingleton|exitCode=21|Target page, context or browser has been closed/i.test(message)) {
    return {
      reason_code: "browser_profile_locked",
      reason: "The dedicated X Chrome profile is still open or locked by another Chrome process.",
      recommended_actions: [
        "Close every Chrome window using the dedicated X Agent profile.",
        "Do not close normal Chrome windows that use a different profile.",
        "Retry after the dedicated process has fully exited."
      ]
    };
  }
  if (/Timeout|timed out/i.test(message)) {
    return {
      reason_code: "browser_timeout",
      reason: "The browser or X page did not reach the required state before the timeout.",
      recommended_actions: [
        "Check network access to x.com and retry once.",
        "If X loads slowly, increase X_AGENT_TIMEOUT_MS up to 120000."
      ]
    };
  }
  if (/ERR_(NAME_NOT_RESOLVED|CONNECTION|TIMED_OUT|PROXY)|getaddrinfo|ECONN/i.test(message)) {
    return {
      reason_code: "network_error",
      reason: "Chrome could not reach X because of a DNS, proxy, VPN, or network connection failure.",
      recommended_actions: ["Check network, proxy, VPN, DNS, and firewall access to x.com."]
    };
  }
  return {
    reason_code: "unexpected_browser_error",
    reason: message,
    recommended_actions: [
      "Run x_session_status for a focused login diagnosis, then inspect the server stderr log."
    ]
  };
}

function errorResult(error: unknown): {
  isError: true;
  content: [{ type: "text"; text: string }];
  structuredContent: Record<string, unknown>;
} {
  const diagnostic = classifyToolError(error);
  return {
    isError: true,
    content: [
      {
        type: "text",
        text: [
          `X News tool error [${diagnostic.reason_code}]: ${diagnostic.reason}`,
          ...diagnostic.recommended_actions.map((action) => `- ${action}`)
        ].join("\n")
      }
    ],
    structuredContent: { error: true, ...diagnostic }
  };
}

const server = new McpServer({ name: "x-news-mcp-server", version: "1.0.0" });

server.registerTool(
  "x_session_status",
  {
    title: "Check X Login Session",
    description:
      "Diagnose the dedicated persistent X session. Returns authenticated state, a stable reason_code, evidence that does not expose cookie values, and specific recovery actions for SSO failures, missing or rejected cookies, security challenges, rate limits, X service errors, page-load failures, and profile locks.",
    inputSchema: SessionSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  },
  async ({ response_format }) => {
    try {
      const status = await withAuthenticatedPage(sessionStatus);
      return {
        content: [{ type: "text", text: formatSession(status, response_format) }],
        structuredContent: { ...status }
      };
    } catch (error) {
      return errorResult(error);
    }
  }
);

server.registerTool(
  "x_search_posts",
  {
    title: "Search Latest X Posts",
    description: `Search X's Latest tab using the dedicated authenticated Chrome profile. This is read-only and returns canonical post URLs, authors, timestamps, text, social context, and visible metric labels.

Use for recent AI news, model leaks, launch rumors, or any focused X query. Supports native X operators in query. Use since/until for recent windows and offset for pagination. Results reflect X at call time and may be affected by X ranking, account access, deletions, or rate limits.`,
    inputSchema: SearchSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  },
  async (input) => {
    try {
      const result = await withAuthenticatedPage((page) => searchPosts(page, input));
      return {
        content: [{ type: "text", text: formatSearchResult(result, input.response_format) }],
        structuredContent: { ...result }
      };
    } catch (error) {
      return errorResult(error);
    }
  }
);

server.registerTool(
  "x_profile_posts",
  {
    title: "Read X Profile Posts",
    description:
      "Read posts currently shown on an X account's Posts tab, including pinned posts, reposts, replies surfaced there, and quoted posts. Read-only; supports pagination.",
    inputSchema: ProfileSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  },
  async ({ handle, limit, offset, response_format }) => {
    try {
      const result = await withAuthenticatedPage((page) => profilePosts(page, handle, limit, offset));
      return {
        content: [{ type: "text", text: formatSearchResult(result, response_format) }],
        structuredContent: { ...result }
      };
    } catch (error) {
      return errorResult(error);
    }
  }
);

server.registerTool(
  "x_get_post",
  {
    title: "Get X Post",
    description:
      "Fetch one X post by its full status URL. Returns canonical URL, author, timestamp, full visible text, social context, and visible metric labels. Read-only.",
    inputSchema: PostSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  },
  async ({ url, response_format }) => {
    try {
      const post = await withAuthenticatedPage((page) => getPost(page, url));
      return {
        content: [{ type: "text", text: formatPost(post, response_format) }],
        structuredContent: { ...post }
      };
    } catch (error) {
      return errorResult(error);
    }
  }
);

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  const pages = process.env.X_AGENT_MAX_CONCURRENT_PAGES ?? "2";
  console.error(
    `x-news-mcp-server running via stdio (shared browser session, max concurrent pages=${pages})`
  );
}

main().catch(async (error: unknown) => {
  console.error("Fatal MCP server error:", error);
  try {
    const { closeSharedBrowser } = await import("./services/browser.js");
    await closeSharedBrowser();
  } catch {
    // ignore cleanup errors on fatal path
  }
  process.exit(1);
});
