import type { PublicReportDetail } from "@/lib/types/public";

/** Serializable slide for the homepage broadcast Hero. */
export type HeroSlide = {
  url: string;
  alt: string;
  category: string;
  reportDate: string;
  signalIndex: number;
};

const IMAGE_TYPES = new Set(["image", "photo", "gif", "animated_gif"]);

function isImageType(type: string | undefined | null): boolean {
  if (!type) return true;
  return IMAGE_TYPES.has(type.toLowerCase());
}

function isUsableUrl(url: string | undefined | null): url is string {
  return typeof url === "string" && url.trim().length > 0;
}

type Candidate = {
  url: string;
  alt: string;
  category: string;
  reportDate: string;
};

function collectFromReport(report: PublicReportDetail): Candidate[] {
  const out: Candidate[] = [];
  const seen = new Set<string>();

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
      alt: (alt ?? "").trim() || "Published report media",
      category: (category ?? "").trim() || "SIGNAL",
      reportDate: report.report_date,
    });
  };

  const digestItems = report.digest?.items ?? [];
  if (digestItems.length > 0) {
    const ordered = [...digestItems].sort((a, b) => a.rank - b.rank);
    for (const item of ordered) {
      const images = [...(item.images ?? [])].sort(
        (a, b) => (a.position ?? 0) - (b.position ?? 0),
      );
      for (const media of images) {
        if (!isImageType(media.type) || !isUsableUrl(media.url)) continue;
        push(media.url, media.alt_text, item.category);
      }
    }
  }

  const posts = [...(report.items ?? [])].sort(
    (a, b) => a.display_order - b.display_order,
  );
  for (const item of posts) {
    const mediaList = [...(item.post.media ?? [])].sort(
      (a, b) => (a.position ?? 0) - (b.position ?? 0),
    );
    for (const media of mediaList) {
      if (!isImageType(media.type) || !isUsableUrl(media.url)) continue;
      push(media.url, media.alt_text, item.category);
    }
  }

  return out;
}

/**
 * Build a Hero playlist from recent report details (latest-first).
 * Round-robins across reports so the last N days all contribute frames
 * instead of filling the reel from only the newest day.
 */
export function extractHeroSlides(
  reports: PublicReportDetail[],
  options?: { maxSlides?: number },
): HeroSlide[] {
  const maxSlides = options?.maxSlides ?? 12;
  if (!reports.length || maxSlides <= 0) return [];

  const pools = reports.map(collectFromReport).filter((p) => p.length > 0);
  if (!pools.length) return [];

  const slides: HeroSlide[] = [];
  const seen = new Set<string>();
  const cursors = pools.map(() => 0);
  let guard = 0;
  const guardMax = maxSlides * pools.length * 2;

  while (slides.length < maxSlides && guard < guardMax) {
    guard += 1;
    let progressed = false;
    for (let i = 0; i < pools.length && slides.length < maxSlides; i += 1) {
      const pool = pools[i];
      while (cursors[i] < pool.length) {
        const candidate = pool[cursors[i]];
        cursors[i] += 1;
        if (seen.has(candidate.url)) continue;
        seen.add(candidate.url);
        slides.push({
          ...candidate,
          signalIndex: slides.length + 1,
        });
        progressed = true;
        break;
      }
    }
    if (!progressed) break;
  }

  return slides;
}
