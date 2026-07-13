export type ResponseFormat = "markdown" | "json";

export interface XMediaItem {
  url: string;
  media_type: "image" | "video" | "gif" | "unknown";
  alt_text: string | null;
}

export interface XPost {
  post_id: string;
  url: string;
  author_name: string;
  author_handle: string;
  created_at: string | null;
  text: string;
  social_context: string | null;
  reply_label: string | null;
  repost_label: string | null;
  like_label: string | null;
  view_label: string | null;
  /** Best-effort media extracted from the timeline card. */
  has_media: boolean;
  media: XMediaItem[];
  /** Quoted / nested post text when visible on the card. */
  quoted_text: string | null;
  quoted_url: string | null;
  quoted_handle: string | null;
  /** Link-card / preview title when present. */
  link_card_title: string | null;
}

export interface SearchResult {
  query: string;
  count: number;
  offset: number;
  posts: XPost[];
  has_more: boolean;
  next_offset: number | null;
}

export type LoginReasonCode =
  | "authenticated"
  | "google_oauth_incomplete"
  | "x_sso_onboarding_stuck"
  | "x_security_challenge"
  | "x_account_restricted"
  | "x_rate_limited"
  | "x_service_error"
  | "auth_cookie_missing"
  | "session_cookie_rejected"
  | "x_page_load_failed"
  | "login_required";

export interface LoginSignals {
  current_url: string;
  title: string;
  http_status: number | null;
  has_auth_cookie: boolean;
  has_csrf_cookie: boolean;
  auth_ui_detected: boolean;
  login_ui_detected: boolean;
  timeline_posts_visible: number;
  blank_dialog_detected: boolean;
  security_challenge_detected: boolean;
  account_restricted_detected: boolean;
  rate_limit_detected: boolean;
  generic_error_detected: boolean;
}

export interface SessionStatus {
  authenticated: boolean;
  reason_code: LoginReasonCode;
  reason: string;
  current_url: string;
  title: string;
  http_status: number | null;
  profile_dir: string;
  has_auth_cookie: boolean;
  has_csrf_cookie: boolean;
  auth_ui_detected: boolean;
  login_ui_detected: boolean;
  timeline_posts_visible: number;
  recommended_actions: string[];
}
