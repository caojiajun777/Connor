import type { PublicMediaItem } from "@/lib/types/public";

export type GalleryLayout =
  | "empty"
  | "single"
  | "pair"
  | "triple"
  | "quad"
  | "overflow";

/**
 * Choose a CSS layout key for 0–4+ media items (tweet-style grids).
 * Only the first four items are laid out; extras use "overflow".
 */
export function getMediaGalleryLayout(
  media: PublicMediaItem[] | undefined | null,
): GalleryLayout {
  const count = media?.length ?? 0;
  if (count <= 0) return "empty";
  if (count === 1) return "single";
  if (count === 2) return "pair";
  if (count === 3) return "triple";
  if (count === 4) return "quad";
  return "overflow";
}

/** Stable identity for a media tile (url + position). */
export function mediaItemKey(item: PublicMediaItem): string {
  return `${item.position}:${item.url}`;
}

/** Cap to four tiles for display; preserve position order. */
export function visibleMediaItems(
  media: PublicMediaItem[],
  max = 4,
): PublicMediaItem[] {
  return [...media]
    .sort((a, b) => a.position - b.position)
    .slice(0, max);
}

/** Drop broken/failed media, then apply the visible-item cap. */
export function usableMediaItems(
  media: PublicMediaItem[],
  failedKeys: Iterable<string>,
  max = 4,
): PublicMediaItem[] {
  const failed = new Set(failedKeys);
  return visibleMediaItems(
    media.filter((item) => !failed.has(mediaItemKey(item))),
    max,
  );
}

export function galleryGridClass(layout: GalleryLayout): string {
  switch (layout) {
    case "single":
      return "grid grid-cols-1";
    case "pair":
      return "grid grid-cols-2 gap-1";
    case "triple":
      return "grid grid-cols-2 grid-rows-2 gap-1";
    case "quad":
    case "overflow":
      return "grid grid-cols-2 grid-rows-2 gap-1";
    default:
      return "hidden";
  }
}
