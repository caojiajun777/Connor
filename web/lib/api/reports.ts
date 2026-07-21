import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

import type {
  PublicReportDetail,
  PublicReportListResponse,
  PublicSiteMeta,
} from "@/lib/types/public";

const API_BASE =
  process.env.CONNOR_PUBLIC_API_BASE?.replace(/\/$/, "") ??
  "http://127.0.0.1:8080";

const USE_FIXTURE =
  process.env.CONNOR_PUBLIC_USE_FIXTURE === "1" &&
  process.env.NODE_ENV !== "production";

const FETCH_TIMEOUT_MS = Number(process.env.CONNOR_PUBLIC_API_TIMEOUT_MS || 12000);

const mediaSchema = z.object({
  type: z.string(),
  url: z.string(),
  width: z.number().nullable().optional().default(null),
  height: z.number().nullable().optional().default(null),
  alt_text: z.string().nullable().optional().default(null),
  position: z.number().optional().default(0),
});

const postSchema = z.object({
  author_name: z.string(),
  author_handle: z.string(),
  author_avatar_url: z.string().nullable().optional().default(null),
  text_original: z.string(),
  text_translated: z.string(),
  posted_at: z.string(),
  original_url: z.string(),
  post_type: z.string(),
  media: z.array(mediaSchema).default([]),
  unavailable: z.boolean().default(false),
  unavailable_reason: z.string().nullable().optional().default(null),
});

const reportItemSchema = z.object({
  display_order: z.number(),
  category: z.string().nullable().optional().default(null),
  post: postSchema,
});

const bodySectionSchema = z.object({
  section_id: z.string().optional().default(""),
  heading: z.string(),
  paragraphs: z.array(z.string()).default([]),
  event_ids: z.array(z.string()).optional().default([]),
  citation_post_ids: z.array(z.string()).optional().default([]),
});

const digestMediaSchema = z.object({
  type: z.string().default("image"),
  url: z.string(),
  width: z.number().nullable().optional().default(null),
  height: z.number().nullable().optional().default(null),
  alt_text: z.string().nullable().optional().default(null),
  position: z.number().optional().default(0),
});

const digestTocEntrySchema = z.object({
  rank: z.number(),
  headline: z.string(),
});

const digestTocSectionSchema = z.object({
  category: z.string(),
  entries: z.array(digestTocEntrySchema).default([]),
});

const digestNewsItemSchema = z.object({
  rank: z.number(),
  category: z.string(),
  headline: z.string(),
  blurb: z.string().default(""),
  body: z.string().default(""),
  links: z.array(z.string()).default([]),
  event_id: z.string().optional().default(""),
  citation_post_ids: z.array(z.string()).optional().default([]),
  images: z.array(digestMediaSchema).default([]),
});

const digestSchema = z.object({
  format: z.string().default("digest_v1"),
  toc: z.array(digestTocSectionSchema).default([]),
  items: z.array(digestNewsItemSchema).default([]),
});

const reportDetailSchema = z.object({
  report_date: z.string(),
  title: z.string(),
  overview: z.string(),
  lead: z.string().optional().default(""),
  keywords: z.array(z.string()).default([]),
  format: z.string().optional().default("essay"),
  body_sections: z.array(bodySectionSchema).default([]),
  digest: digestSchema.nullable().optional().default(null),
  item_count: z.number(),
  source_post_count: z.number(),
  published_at: z.string().nullable().optional().default(null),
  previous_report_date: z.string().nullable().optional().default(null),
  next_report_date: z.string().nullable().optional().default(null),
  items: z.array(reportItemSchema).default([]),
});

const listItemSchema = z.object({
  report_date: z.string(),
  title: z.string(),
  overview_excerpt: z.string(),
  item_count: z.number(),
  published_at: z.string().nullable().optional().default(null),
  is_latest: z.boolean().default(false),
  keywords: z.array(z.string()).default([]),
});

const listResponseSchema = z.object({
  items: z.array(listItemSchema),
  next_cursor: z.string().nullable().optional().default(null),
});

const metaSchema = z.object({
  latest_report_date: z.string().nullable().optional().default(null),
  latest_title: z.string().nullable().optional().default(null),
  system_status: z.string().default("online"),
});

export class PublicApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "PublicApiError";
    this.status = status;
  }
}

async function fetchJson<T>(
  url: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const res = await fetch(url, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });

    if (!res.ok) {
      throw new PublicApiError(
        `Public API ${res.status}`,
        res.status,
      );
    }

    const data: unknown = await res.json();
    return schema.parse(data);
  } catch (err) {
    if (err instanceof PublicApiError) throw err;
    if (err instanceof Error && err.name === "AbortError") {
      throw new PublicApiError("Public API timeout", 504);
    }
    throw new PublicApiError(
      err instanceof Error ? err.message : "Public API request failed",
      502,
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function loadFixtureDetail(): Promise<PublicReportDetail> {
  const candidates = [
    path.join(process.cwd(), "fixtures", "public-report.json"),
    path.join(process.cwd(), "..", "fixtures", "public-report.json"),
  ];

  let lastError: unknown;
  for (const file of candidates) {
    try {
      const raw = await readFile(file, "utf8");
      return reportDetailSchema.parse(JSON.parse(raw));
    } catch (err) {
      lastError = err;
    }
  }
  throw new PublicApiError(
    `Fixture not found or invalid (CONNOR_PUBLIC_USE_FIXTURE=1). Last error: ${String(lastError)}`,
    500,
  );
}

export async function getSiteMeta(): Promise<PublicSiteMeta> {
  if (USE_FIXTURE) {
    const detail = await loadFixtureDetail();
    return {
      latest_report_date: detail.report_date,
      latest_title: detail.title,
      system_status: "online",
    };
  }
  return fetchJson(`${API_BASE}/api/public/meta`, metaSchema);
}

export async function listReports(params?: {
  year?: number;
  month?: number;
  limit?: number;
  cursor?: string;
}): Promise<PublicReportListResponse> {
  if (USE_FIXTURE) {
    const detail = await loadFixtureDetail();
    const lead = (detail.lead || detail.overview || "").trim();
    return {
      items: [
        {
          report_date: detail.report_date,
          title: detail.title,
          overview_excerpt: lead.slice(0, 160),
          item_count: detail.item_count,
          published_at: detail.published_at,
          is_latest: true,
          keywords: detail.keywords,
        },
      ],
      next_cursor: null,
    };
  }

  const qs = new URLSearchParams();
  if (params?.year != null) qs.set("year", String(params.year));
  if (params?.month != null) qs.set("month", String(params.month));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return fetchJson(
    `${API_BASE}/api/public/reports${suffix}`,
    listResponseSchema,
  );
}

export async function getReport(
  reportDate: string,
): Promise<PublicReportDetail> {
  if (USE_FIXTURE) {
    const detail = await loadFixtureDetail();
    if (detail.report_date !== reportDate) {
      throw new PublicApiError("report not found in fixture", 404);
    }
    return detail;
  }

  try {
    return await fetchJson(
      `${API_BASE}/api/public/reports/${encodeURIComponent(reportDate)}`,
      reportDetailSchema,
    );
  } catch (err) {
    if (err instanceof PublicApiError) throw err;
    throw new PublicApiError(
      err instanceof Error ? err.message : "Failed to load report",
      500,
    );
  }
}

export function isValidReportDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}
