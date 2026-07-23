import type { Page } from "playwright-core";
import { profileDir, timeoutMs, X_BASE_URL } from "../constants.js";
import { firstTweetWaitMs, nextScrollDecision } from "./collect-budget.js";
import type {
  LoginReasonCode,
  LoginSignals,
  SearchResult,
  SessionStatus,
  XPost
} from "../types.js";

const STATUS_PATH = /^\/([A-Za-z0-9_]+)\/status\/(\d+)/;
const AUTH_SELECTOR =
  '[data-testid="SideNav_AccountSwitcher_Button"], a[data-testid="AppTabBar_Home_Link"]';
const LOGIN_SELECTOR = 'input[autocomplete="username"], input[name="text"]';

interface LoginClassification {
  authenticated: boolean;
  reason_code: LoginReasonCode;
  reason: string;
  recommended_actions: string[];
}

export class XAuthenticationError extends Error {
  readonly status: SessionStatus;

  constructor(status: SessionStatus) {
    super(`X authentication failed [${status.reason_code}]: ${status.reason}`);
    this.name = "XAuthenticationError";
    this.status = status;
  }
}

export function classifyLoginState(signals: LoginSignals): LoginClassification {
  if (signals.auth_ui_detected && signals.has_auth_cookie) {
    return {
      authenticated: true,
      reason_code: "authenticated",
      reason: "The persistent X session is authenticated and account navigation is visible.",
      recommended_actions: []
    };
  }
  if (/accounts\.google\.com/i.test(signals.current_url)) {
    return {
      authenticated: false,
      reason_code: "google_oauth_incomplete",
      reason: "The Google OAuth flow has not returned a completed X session.",
      recommended_actions: [
        "Finish Google consent in the dedicated native Chrome window.",
        "Confirm the Google email exactly matches the email attached to the existing X account.",
        "After X Home appears, close the dedicated Chrome window before retrying."
      ]
    };
  }
  if (/\/i\/jf\/onboarding\/web\/sso/i.test(signals.current_url) || signals.blank_dialog_detected) {
    return {
      authenticated: false,
      reason_code: "x_sso_onboarding_stuck",
      reason: "Google verification returned to X, but X's SSO onboarding dialog did not finish rendering or committing the login.",
      recommended_actions: [
        "Open https://x.com/home in a new tab in the same dedicated Chrome window.",
        "If Home does not load, retry at https://x.com/i/flow/login or use X username/password.",
        "Ensure the selected Google email is linked to the X account."
      ]
    };
  }
  if (signals.account_restricted_detected) {
    return {
      authenticated: false,
      reason_code: "x_account_restricted",
      reason: "X indicates that the account is locked, suspended, or otherwise restricted.",
      recommended_actions: [
        "Complete X account recovery in the dedicated browser.",
        "Do not repeatedly retry automation until the restriction is cleared."
      ]
    };
  }
  if (signals.security_challenge_detected) {
    return {
      authenticated: false,
      reason_code: "x_security_challenge",
      reason: "X requires an interactive identity, CAPTCHA, phone, email, or unusual-activity verification step.",
      recommended_actions: [
        "Open the dedicated native Chrome login window and complete verification manually.",
        "Close that browser window after X Home is visible, then retry the Agent."
      ]
    };
  }
  if (signals.http_status === 429 || signals.rate_limit_detected) {
    return {
      authenticated: false,
      reason_code: "x_rate_limited",
      reason: "X is rate-limiting this session or network.",
      recommended_actions: [
        "Wait before retrying and reduce search frequency.",
        "Avoid running multiple X Agent searches concurrently."
      ]
    };
  }
  if ((signals.http_status !== null && signals.http_status >= 500) || signals.generic_error_detected) {
    return {
      authenticated: false,
      reason_code: "x_service_error",
      reason: "X returned a service error or generic page failure.",
      recommended_actions: [
        "Retry once after a short wait.",
        "If it persists, open X Home manually to check service availability."
      ]
    };
  }
  if (!signals.has_auth_cookie) {
    return {
      authenticated: false,
      reason_code: "auth_cookie_missing",
      reason: "The dedicated Chrome profile does not contain X's auth_token cookie, so login was not persisted.",
      recommended_actions: [
        "Run npm run login and finish login in the dedicated native Chrome window.",
        "Wait until X Home appears, then close the entire dedicated window normally."
      ]
    };
  }
  if (!signals.auth_ui_detected && !signals.title && !signals.login_ui_detected) {
    return {
      authenticated: false,
      reason_code: "x_page_load_failed",
      reason: "X did not render either the authenticated shell or login interface before the diagnostic timeout.",
      recommended_actions: [
        "Check network, VPN, DNS, and access to x.com and abs.twimg.com.",
        "Retry once; if it repeats, open X Home manually in the dedicated profile."
      ]
    };
  }
  if (signals.has_auth_cookie && !signals.auth_ui_detected) {
    return {
      authenticated: false,
      reason_code: "session_cookie_rejected",
      reason: "An auth_token cookie exists, but X did not accept it as an authenticated web session.",
      recommended_actions: [
        "Open the dedicated native Chrome profile and sign in again.",
        "Complete any verification manually and close the window normally.",
        "If necessary, revoke the old X session before creating a new one."
      ]
    };
  }
  return {
    authenticated: false,
    reason_code: "login_required",
    reason: "X is showing a login interface and no authenticated account shell is available.",
    recommended_actions: ["Run npm run login and complete sign-in in the dedicated native Chrome window."]
  };
}

export function buildSearchQuery(input: {
  query: string;
  since?: string;
  until?: string;
  lang?: string;
}): string {
  const parts = [input.query.trim()];
  if (input.since && !/(^|\s)since:/.test(input.query)) parts.push(`since:${input.since}`);
  if (input.until && !/(^|\s)until:/.test(input.query)) parts.push(`until:${input.until}`);
  if (input.lang && !/(^|\s)lang:/.test(input.query)) parts.push(`lang:${input.lang}`);
  return parts.join(" ");
}

export function normalizePostUrl(value: string): string {
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    throw new Error("A numeric post ID alone is ambiguous. Pass the full X post URL.");
  }
  const url = new URL(trimmed, X_BASE_URL);
  if (url.hostname !== "x.com" && url.hostname !== "twitter.com") {
    throw new Error("Post URL must use x.com or twitter.com.");
  }
  if (!STATUS_PATH.test(url.pathname)) {
    throw new Error("Expected an X post URL such as https://x.com/user/status/123.");
  }
  return `${X_BASE_URL}${url.pathname}`;
}

async function waitForAuthenticationState(page: Page): Promise<void> {
  if (/\/i\/(flow\/login|jf\/onboarding)/.test(page.url())) return;
  await Promise.race([
    page.locator(AUTH_SELECTOR).first().waitFor({ state: "attached", timeout: timeoutMs() }),
    page.locator(LOGIN_SELECTOR).first().waitFor({ state: "attached", timeout: timeoutMs() })
  ]).catch(() => undefined);
}

async function inspectCurrentSession(
  page: Page,
  httpStatus: number | null = null
): Promise<SessionStatus> {
  await waitForAuthenticationState(page);
  const cookies = await page.context().cookies(X_BASE_URL);
  const cookieNames = new Set(cookies.map((cookie) => cookie.name));
  const bodyText = await page
    .locator("body")
    .innerText({ timeout: Math.min(timeoutMs(), 5_000) })
    .catch(() => "");
  const normalizedText = bodyText.toLowerCase();
  const dialogs = page.locator('[role="dialog"]');
  const dialogCount = await dialogs.count();
  let blankDialogDetected = false;
  if (dialogCount > 0) {
    const firstDialogText = await dialogs.first().innerText({ timeout: 2_000 }).catch(() => "");
    blankDialogDetected = firstDialogText.trim().length === 0;
  }

  const signals: LoginSignals = {
    current_url: page.url(),
    title: await page.title().catch(() => ""),
    http_status: httpStatus,
    has_auth_cookie: cookieNames.has("auth_token"),
    has_csrf_cookie: cookieNames.has("ct0"),
    auth_ui_detected: (await page.locator(AUTH_SELECTOR).count()) > 0,
    login_ui_detected: (await page.locator(LOGIN_SELECTOR).count()) > 0,
    timeline_posts_visible: await page.locator('article[data-testid="tweet"]').count(),
    blank_dialog_detected: blankDialogDetected,
    security_challenge_detected:
      /verify your identity|unusual activity|captcha|arkose|验证你的身份|异常活动|验证码/.test(
        normalizedText
      ) || /\/account\/access|\/i\/flow\/(consent|challenge)/.test(page.url()),
    account_restricted_detected:
      /account.{0,30}(suspended|locked)|your account is locked|账号.{0,20}(冻结|锁定)/.test(
        normalizedText
      ),
    rate_limit_detected: /rate limit|too many requests|请求过多|稍后再试/.test(normalizedText),
    generic_error_detected: /something went wrong|try reloading|出错了|重新加载/.test(
      normalizedText
    )
  };
  const classification = classifyLoginState(signals);
  return {
    ...classification,
    current_url: signals.current_url,
    title: signals.title,
    http_status: signals.http_status,
    profile_dir: profileDir(),
    has_auth_cookie: signals.has_auth_cookie,
    has_csrf_cookie: signals.has_csrf_cookie,
    auth_ui_detected: signals.auth_ui_detected,
    login_ui_detected: signals.login_ui_detected,
    timeline_posts_visible: signals.timeline_posts_visible
  };
}

async function assertAuthenticated(page: Page): Promise<void> {
  const status = await inspectCurrentSession(page);
  if (status.authenticated) return;
  throw new XAuthenticationError(status);
}

export async function sessionStatus(page: Page): Promise<SessionStatus> {
  const response = await page.goto(`${X_BASE_URL}/home`, { waitUntil: "domcontentloaded" });
  return inspectCurrentSession(page, response?.status() ?? null);
}

export async function extractPosts(page: Page): Promise<XPost[]> {
  return page.evaluate(() => {
    const absolute = (href: string): string => new URL(href, "https://x.com").toString();
    const articles = Array.from(document.querySelectorAll<HTMLElement>('article[data-testid="tweet"]'));
    return articles.flatMap((article): XPost[] => {
      const time = article.querySelector<HTMLTimeElement>("time");
      const statusAnchor = time?.closest<HTMLAnchorElement>('a[href*="/status/"]');
      const href = statusAnchor?.getAttribute("href") ?? "";
      const match = href.match(/^\/([A-Za-z0-9_]+)\/status\/(\d+)/);
      if (!match) return [];
      const matchedAuthor = match[1]!;
      const matchedPostId = match[2]!;

      const userName = article.querySelector<HTMLElement>('[data-testid="User-Name"]');
      const userLinks = Array.from(userName?.querySelectorAll<HTMLAnchorElement>('a[href^="/"]') ?? []);
      const handleElement = userLinks
        .flatMap((link) => Array.from(link.querySelectorAll<HTMLElement>("span")))
        .find((span) => (span.textContent ?? "").trim().startsWith("@"));
      const handle = (handleElement?.textContent ?? `@${matchedAuthor}`).trim();
      const name =
        Array.from(userName?.querySelectorAll<HTMLElement>("span") ?? [])
          .map((span) => (span.textContent ?? "").trim())
          .find((text) => text && !text.startsWith("@")) ?? matchedAuthor;

      const metric = (testId: string): string | null => {
        const element = article.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
        return element?.getAttribute("aria-label") ?? element?.textContent?.trim() ?? null;
      };
      const viewLink = article.querySelector<HTMLElement>('a[href$="/analytics"]');
      const primaryTextNode = article.querySelector<HTMLElement>('[data-testid="tweetText"]');
      const text = primaryTextNode?.innerText.trim() ?? "";
      const context = article
        .querySelector<HTMLElement>('[data-testid="socialContext"]')
        ?.innerText.trim();

      // Media: photos, gifs, videos attached to this card (best-effort DOM scrape).
      const media: Array<{ url: string; media_type: "image" | "video" | "gif" | "unknown"; alt_text: string | null }> =
        [];
      const seenMedia = new Set<string>();
      const pushMedia = (url: string, mediaType: "image" | "video" | "gif" | "unknown", alt: string | null) => {
        if (!url || seenMedia.has(url)) return;
        seenMedia.add(url);
        media.push({ url, media_type: mediaType, alt_text: alt });
      };
      for (const img of Array.from(article.querySelectorAll<HTMLImageElement>("img"))) {
        const src = img.currentSrc || img.src || "";
        if (!/pbs\.twimg\.com|ton\.twitter\.com|video\.twimg\.com/.test(src)) continue;
        if (/profile_images|emoji|hashflag/.test(src)) continue;
        const alt = (img.getAttribute("alt") || "").trim();
        const mediaType = /tweet_video_thumb|\.gif/i.test(src) ? "gif" : "image";
        pushMedia(src, mediaType, alt || null);
      }
      for (const video of Array.from(article.querySelectorAll<HTMLVideoElement>("video"))) {
        const src = video.currentSrc || video.src || video.querySelector("source")?.src || "";
        if (src) pushMedia(src, "video", video.getAttribute("aria-label"));
        else if (video.poster) pushMedia(video.poster, "video", video.getAttribute("aria-label"));
      }
      if (article.querySelector('[data-testid="videoPlayer"], [data-testid="videoComponent"]')) {
        // Ensure has_media even when src is blob:/lazy.
        if (media.length === 0) pushMedia(`video://${matchedPostId}`, "video", null);
      }

      // Quoted post: nested status link + secondary tweetText not equal to primary text.
      let quoted_text: string | null = null;
      let quoted_url: string | null = null;
      let quoted_handle: string | null = null;
      const statusLinks = Array.from(article.querySelectorAll<HTMLAnchorElement>('a[href*="/status/"]'));
      for (const link of statusLinks) {
        const qHref = link.getAttribute("href") ?? "";
        const qMatch = qHref.match(/^\/([A-Za-z0-9_]+)\/status\/(\d+)/);
        if (!qMatch) continue;
        if (qMatch[2] === matchedPostId) continue;
        quoted_url = absolute(qHref.split("?")[0] ?? qHref);
        quoted_handle = qMatch[1] ?? null;
        break;
      }
      const textNodes = Array.from(article.querySelectorAll<HTMLElement>('[data-testid="tweetText"]'));
      if (textNodes.length > 1) {
        const nested = textNodes
          .slice(1)
          .map((node) => node.innerText.trim())
          .find((value) => value && value !== text);
        if (nested) quoted_text = nested;
      }

      // Link card / preview title.
      let link_card_title: string | null = null;
      const card =
        article.querySelector<HTMLElement>('[data-testid="card.wrapper"]') ??
        article.querySelector<HTMLElement>('[data-testid="card.layoutLarge.media"]') ??
        article.querySelector<HTMLElement>('[data-testid="card.layoutSmall.media"]');
      if (card) {
        const leafTexts = Array.from(card.querySelectorAll("span, div, a"))
          .filter((el) => el.children.length === 0)
          .map((el) => (el.textContent ?? "").trim())
          .filter((text) => text.length > 0 && text.length < 240);
        if (leafTexts.length > 0) {
          link_card_title = leafTexts[0] ?? null;
        } else {
          const fallback = card.innerText
            .trim()
            .split(/\n+/)
            .map((line) => line.trim())
            .find(Boolean);
          link_card_title = fallback || null;
        }
      }

      return [
        {
          post_id: matchedPostId,
          url: absolute(`/${matchedAuthor}/status/${matchedPostId}`),
          author_name: name,
          author_handle: handle,
          created_at: time?.getAttribute("datetime") ?? null,
          text,
          social_context: context || null,
          reply_label: metric("reply"),
          repost_label: metric("retweet"),
          like_label: metric("like") ?? metric("unlike"),
          view_label: viewLink?.getAttribute("aria-label") ?? viewLink?.innerText.trim() ?? null,
          has_media: media.length > 0,
          media,
          quoted_text,
          quoted_url,
          quoted_handle,
          link_card_title
        }
      ];
    });
  });
}

type CollectPostsResult = {
  posts: XPost[];
  stopReason: "enough" | "empty_first_screen" | "max_passes" | "scroll";
};

async function collectPosts(page: Page, needed: number): Promise<CollectPostsResult> {
  const seen = new Map<string, XPost>();
  let stopReason: CollectPostsResult["stopReason"] = "max_passes";
  for (let pass = 0; pass < 12 && seen.size < needed; pass += 1) {
    for (const post of await extractPosts(page)) seen.set(post.post_id, post);
    const decision = nextScrollDecision({
      pass,
      seenCount: seen.size,
      needed
    });
    stopReason = decision.reason;
    if (!decision.continueScrolling) break;
    await page.mouse.wheel(0, 1400);
    await page.waitForTimeout(700);
  }
  return { posts: [...seen.values()], stopReason };
}

/** Soft blocks that still leave the auth chrome visible (rate-limit / generic error). */
async function softBlockStatus(page: Page): Promise<SessionStatus | null> {
  const bodyText = await page
    .locator("body")
    .innerText({ timeout: Math.min(timeoutMs(), 5_000) })
    .catch(() => "");
  const normalizedText = bodyText.toLowerCase();
  const rateLimited =
    /rate limit|too many requests|请求过多|稍后再试|retry later/.test(normalizedText);
  const serviceError = /something went wrong|try reloading|出错了|重新加载/.test(normalizedText);
  if (!rateLimited && !serviceError) return null;

  const classification = rateLimited
    ? {
        authenticated: false as const,
        reason_code: "x_rate_limited" as const,
        reason: "X is rate-limiting this session or network.",
        recommended_actions: [
          "Wait before retrying and reduce search frequency.",
          "Avoid running multiple X Agent searches concurrently."
        ]
      }
    : {
        authenticated: false as const,
        reason_code: "x_service_error" as const,
        reason: "X returned a service error or generic page failure.",
        recommended_actions: [
          "Retry once after a short wait.",
          "If it persists, open X Home manually to check service availability."
        ]
      };

  return {
    ...classification,
    current_url: page.url(),
    title: await page.title().catch(() => ""),
    http_status: null,
    profile_dir: profileDir(),
    has_auth_cookie: true,
    has_csrf_cookie: true,
    auth_ui_detected: true,
    login_ui_detected: false,
    timeline_posts_visible: await page.locator('article[data-testid="tweet"]').count()
  };
}

export async function searchPosts(
  page: Page,
  input: {
    query: string;
    limit: number;
    offset: number;
    since?: string;
    until?: string;
    lang?: string;
  }
): Promise<SearchResult> {
  const query = buildSearchQuery(input);
  const url = `${X_BASE_URL}/search?q=${encodeURIComponent(query)}&src=typed_query&f=live`;
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await assertAuthenticated(page);
  await page
    .locator('article[data-testid="tweet"]')
    .first()
    .waitFor({ state: "visible", timeout: firstTweetWaitMs(timeoutMs()) })
    .catch(() => undefined);

  const collected = await collectPosts(page, input.offset + input.limit + 1);
  const posts = collected.posts.slice(input.offset, input.offset + input.limit);
  const hasMore = collected.posts.length > input.offset + input.limit;
  return {
    query,
    count: posts.length,
    offset: input.offset,
    posts,
    has_more: hasMore,
    next_offset: hasMore ? input.offset + posts.length : null,
    scroll_stop_reason: collected.stopReason,
    first_screen_empty: collected.stopReason === "empty_first_screen"
  };
}

export async function profilePosts(
  page: Page,
  handle: string,
  limit: number,
  offset: number
): Promise<SearchResult> {
  const cleanHandle = handle.replace(/^@/, "");
  const needed = offset + limit + 1;

  const loadProfile = async (): Promise<CollectPostsResult> => {
    await page.goto(`${X_BASE_URL}/${cleanHandle}`, { waitUntil: "domcontentloaded" });
    await assertAuthenticated(page);
    await page
      .locator('article[data-testid="tweet"]')
      .first()
      .waitFor({ state: "visible", timeout: firstTweetWaitMs(timeoutMs()) })
      .catch(() => undefined);
    return collectPosts(page, needed);
  };

  let collected = await loadProfile();

  // Fail-forward: classify soft blocks, but do not burn time on reload loops.
  // Empty / rate-limited handles are retried in a later collect pass.
  if (collected.posts.length === 0) {
    const soft = await softBlockStatus(page);
    if (soft) throw new XAuthenticationError(soft);
  }

  const posts = collected.posts.slice(offset, offset + limit);
  const hasMore = collected.posts.length > offset + limit;
  return {
    query: `from:${cleanHandle}`,
    count: posts.length,
    offset,
    posts,
    has_more: hasMore,
    next_offset: hasMore ? offset + posts.length : null,
    scroll_stop_reason: collected.stopReason,
    first_screen_empty: collected.posts.length === 0 && collected.stopReason === "empty_first_screen"
  };
}

export async function getPost(page: Page, postUrl: string): Promise<XPost> {
  const normalized = normalizePostUrl(postUrl);
  await page.goto(normalized, { waitUntil: "domcontentloaded" });
  await assertAuthenticated(page);
  await page
    .locator('article[data-testid="tweet"]')
    .first()
    .waitFor({ state: "visible", timeout: timeoutMs() });
  const posts = await extractPosts(page);
  const expectedId = normalized.match(/\/status\/(\d+)/)?.[1];
  const exact = posts.find((post) => post.post_id === expectedId);
  if (!exact) throw new Error("The requested X post was not present on the loaded page.");
  return exact;
}
