/** Allow http(s) URLs and same-origin absolute paths (e.g. `/media/...`). */
export function safeHttpUrl(url: string | null | undefined): string | null {
  const raw = (url ?? "").trim();
  if (!raw) return null;

  // Same-origin path used for local media via Next rewrites.
  if (raw.startsWith("/") && !raw.startsWith("//")) {
    if (raw.includes("\\") || raw.includes("\0")) return null;
    return raw;
  }

  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

const MEDIA_HOST_ALLOWLIST = new Set([
  "pbs.twimg.com",
  "abs.twimg.com",
  "video.twimg.com",
  "ton.twitter.com",
]);

/** Stricter helper for <img>/<video src>: only /media/* or allowlisted HTTPS CDNs. */
export function safeMediaSrc(url: string | null | undefined): string | null {
  const raw = (url ?? "").trim();
  if (!raw) return null;

  if (raw.startsWith("/") && !raw.startsWith("//")) {
    if (raw.includes("\\") || raw.includes("\0")) return null;
    if (!raw.startsWith("/media/")) return null;
    return raw;
  }

  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:") return null;
    const host = parsed.hostname.toLowerCase();
    if (
      MEDIA_HOST_ALLOWLIST.has(host) ||
      [...MEDIA_HOST_ALLOWLIST].some((allowed) => host.endsWith(`.${allowed}`))
    ) {
      return parsed.toString();
    }
    return null;
  } catch {
    return null;
  }
}
