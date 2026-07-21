/** Types matching FastAPI public schemas exactly. */

export interface PublicMediaItem {
  type: string;
  url: string;
  width: number | null;
  height: number | null;
  alt_text: string | null;
  position: number;
}

export interface PublicPostPayload {
  author_name: string;
  author_handle: string;
  author_avatar_url: string | null;
  text_original: string;
  text_translated: string;
  posted_at: string;
  original_url: string;
  post_type: string;
  media: PublicMediaItem[];
  unavailable: boolean;
  unavailable_reason: string | null;
}

export interface PublicReportItem {
  display_order: number;
  category: string | null;
  post: PublicPostPayload;
}

export interface PublicBodySection {
  section_id: string;
  heading: string;
  paragraphs: string[];
  event_ids: string[];
  citation_post_ids: string[];
}

export interface PublicDigestMedia {
  type: string;
  url: string;
  width: number | null;
  height: number | null;
  alt_text: string | null;
  position: number;
}

export interface PublicDigestTocEntry {
  rank: number;
  headline: string;
}

export interface PublicDigestTocSection {
  category: string;
  entries: PublicDigestTocEntry[];
}

export interface PublicDigestNewsItem {
  rank: number;
  category: string;
  headline: string;
  blurb: string;
  body: string;
  links: string[];
  event_id: string;
  citation_post_ids: string[];
  images: PublicDigestMedia[];
}

export interface PublicDigestDocument {
  format: string;
  toc: PublicDigestTocSection[];
  items: PublicDigestNewsItem[];
}

export interface PublicReportDetail {
  report_date: string;
  title: string;
  /** Writer 导语（与 lead 同义；兼容旧字段） */
  overview: string;
  lead: string;
  keywords: string[];
  /** essay | digest_v1 */
  format: string;
  body_sections: PublicBodySection[];
  digest: PublicDigestDocument | null;
  item_count: number;
  source_post_count: number;
  published_at: string | null;
  previous_report_date: string | null;
  next_report_date: string | null;
  /** Source posts (original + faithful translation); not the narrative body. */
  items: PublicReportItem[];
}

export interface PublicReportListItem {
  report_date: string;
  title: string;
  overview_excerpt: string;
  item_count: number;
  published_at: string | null;
  is_latest: boolean;
  keywords: string[];
}

export interface PublicReportListResponse {
  items: PublicReportListItem[];
  next_cursor: string | null;
}

export interface PublicSiteMeta {
  latest_report_date: string | null;
  latest_title: string | null;
  system_status: string;
}
