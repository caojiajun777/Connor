import type { PublicReportDetail } from "@/lib/types/public";

/** Serializable slide for the homepage broadcast Hero. */
export type HeroBroadcastImage = {
  url: string;
  alt: string;
  category: string;
  reportDate: string;
  /** 1-based index for corner meta (CONNOR SIGNAL 01). */
  signalIndex: number;
};

const IMAGE_TYPES = new Set(["image", "photo", "gif"]);

function isImageType(type: string | undefined | null): boolean {
  if (!type) return true;
  return IMAGE_TYPES.has(type.toLowerCase());
}

function isUsableUrl(url: string | undefined | null): url is string {
  return typeof url === "string" && url.trim().length > 0;
}

/**
 * Collect real published-report images in event order.
 * Prefers digest item images, then source-post media; dedupes by URL.
 */
export function extractHeroImagesFromReport(
  detail: PublicReportDetail,
): Omit<HeroBroadcastImage, "signalIndex">[] {
  const seen = new Set<string>();
  const out: Omit<HeroBroadcastImage, "signalIndex">[] = [];

  const push = (
    url: string,
    alt: string | null | undefined,
    category: string | null | undefined,
  ) => {
    const key = url.trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({
      url: key,
      alt: (alt ?? "").trim() || "Published report image",
      category: (category ?? "").trim() || "SIGNAL",
      reportDate: detail.report_date,
    });
  };

  const digestItems = detail.digest?.items
    ? [...detail.digest.items].sort((a, b) => a.rank - b.rank)
    : [];

  for (const item of digestItems) {
    const images = [...(item.images ?? [])].sort(
      (a, b) => (a.position ?? 0) - (b.position ?? 0),
    );
    for (const img of images) {
      if (!isImageType(img.type) || !isUsableUrl(img.url)) continue;
      push(img.url, img.alt_text, item.category);
    }
  }

  const posts = [...(detail.items ?? [])].sort(
    (a, b) => a.display_order - b.display_order,
  );
  for (const item of posts) {
    const media = [...(item.post?.media ?? [])].sort(
      (a, b) => (a.position ?? 0) - (b.position ?? 0),
    );
    for (const m of media) {
      if (!isImageType(m.type) || !isUsableUrl(m.url)) continue;
      push(m.url, m.alt_text, item.category);
    }
  }

  return out;
}

/**
 * Build a modest Hero playlist from newest → older report details.
 * Caps length to avoid large client payloads.
 */
export function buildHeroPlaylist(
  details: PublicReportDetail[],
  maxImages = 8,
): HeroBroadcastImage[] {
  const collected: Omit<HeroBroadcastImage, "signalIndex">[] = [];
  const seen = new Set<string>();

  for (const detail of details) {
    for (const img of extractHeroImagesFromReport(detail)) {
      if (seen.has(img.url)) continue;
      seen.add(img.url);
      collected.push(img);
      if (collected.length >= maxImages) break;
    }
    if (collected.length >= maxImages) break;
  }

  return collected.map((img, i) => ({
    ...img,
    signalIndex: i + 1,
  }));
}
