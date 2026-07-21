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
