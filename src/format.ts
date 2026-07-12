import { CHARACTER_LIMIT } from "./constants.js";
import type { SearchResult, SessionStatus, XPost } from "./types.js";

function postMarkdown(post: XPost, index?: number): string {
  const heading = index === undefined ? "## Post" : `## ${index + 1}. ${post.author_name}`;
  return [
    heading,
    `- **Author:** ${post.author_name} (${post.author_handle})`,
    `- **Time:** ${post.created_at ?? "Unknown"}`,
    post.social_context ? `- **Context:** ${post.social_context}` : "",
    `- **URL:** ${post.url}`,
    "",
    post.text || "_(No text; media-only post)_"
  ]
    .filter(Boolean)
    .join("\n");
}

export function formatSearchResult(result: SearchResult, format: "markdown" | "json"): string {
  let output =
    format === "json"
      ? JSON.stringify(result, null, 2)
      : [
          `# X Search: ${result.query}`,
          `Showing ${result.count} post(s) from offset ${result.offset}.`,
          "",
          ...result.posts.map((post, index) => postMarkdown(post, index)),
          "",
          result.has_more ? `More results available at offset ${result.next_offset}.` : "No more loaded results."
        ].join("\n");

  if (output.length > CHARACTER_LIMIT) {
    output = `${output.slice(0, CHARACTER_LIMIT - 160)}\n\n_Response truncated. Reduce limit or use a narrower query._`;
  }
  return output;
}

export function formatPost(post: XPost, format: "markdown" | "json"): string {
  return format === "json" ? JSON.stringify(post, null, 2) : postMarkdown(post);
}

export function formatSession(status: SessionStatus, format: "markdown" | "json"): string {
  return format === "json"
    ? JSON.stringify(status, null, 2)
    : [
        `# X Session: ${status.authenticated ? "Authenticated" : "Login error"}`,
        `- **Reason code:** ${status.reason_code}`,
        `- **Reason:** ${status.reason}`,
        `- **Profile:** ${status.profile_dir}`,
        `- **Current URL:** ${status.current_url}`,
        `- **HTTP status:** ${status.http_status ?? "Unknown"}`,
        `- **Auth cookie present:** ${status.has_auth_cookie}`,
        `- **CSRF cookie present:** ${status.has_csrf_cookie}`,
        `- **Account UI detected:** ${status.auth_ui_detected}`,
        `- **Timeline posts visible:** ${status.timeline_posts_visible}`,
        ...(status.recommended_actions.length
          ? ["", "## Recommended actions", ...status.recommended_actions.map((action) => `- ${action}`)]
          : [])
      ].join("\n");
}
