import { format, formatDistanceToNowStrict, parseISO } from "date-fns";

export function formatReportDate(date: string): string {
  try {
    return format(parseISO(date), "MMM d, yyyy");
  } catch {
    return date;
  }
}

export function formatReportDateLong(date: string): string {
  try {
    return format(parseISO(date), "MMMM d, yyyy");
  } catch {
    return date;
  }
}

export function formatPostedAt(iso: string): string {
  try {
    const d = parseISO(iso);
    return format(d, "MMM d, yyyy · HH:mm");
  } catch {
    return iso;
  }
}

export function formatRelative(iso: string): string {
  try {
    return formatDistanceToNowStrict(parseISO(iso), { addSuffix: true });
  } catch {
    return iso;
  }
}

export function monthLabel(year: number, month: number): string {
  const d = new Date(Date.UTC(year, month - 1, 1));
  return format(d, "MMMM yyyy");
}

export function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** Editorial rank: 1 → "01". */
export function padRank(rank: number): string {
  return String(Math.max(0, rank)).padStart(2, "0");
}

/** Extract X/Twitter status id from a post URL when present. */
export function postIdFromUrl(url: string): string | null {
  const match = url.match(/\/status\/([A-Za-z0-9_]+)/i);
  return match?.[1] ?? null;
}

/** "OpenAI, Anthropic +2" style handle summary. */
export function summarizeHandles(
  handles: string[],
  maxVisible = 2,
): string {
  const unique: string[] = [];
  const seen = new Set<string>();
  for (const raw of handles) {
    const h = raw.replace(/^@/, "").trim();
    if (!h) continue;
    const key = h.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(h);
  }
  if (unique.length === 0) return "";
  if (unique.length <= maxVisible) return unique.join(", ");
  return `${unique.slice(0, maxVisible).join(", ")} +${unique.length - maxVisible}`;
}
