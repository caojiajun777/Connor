import { describe, expect, it } from "vitest";

import {
  galleryGridClass,
  getMediaGalleryLayout,
  mediaItemKey,
  usableMediaItems,
  visibleMediaItems,
} from "./media-gallery";
import type { PublicMediaItem } from "./types/public";

function media(n: number): PublicMediaItem[] {
  return Array.from({ length: n }, (_, i) => ({
    type: "photo",
    url: `/media/${i}.jpg`,
    width: 800,
    height: 600,
    alt_text: null,
    position: n - i,
  }));
}

describe("getMediaGalleryLayout", () => {
  it("maps counts to layout keys", () => {
    expect(getMediaGalleryLayout([])).toBe("empty");
    expect(getMediaGalleryLayout(media(1))).toBe("single");
    expect(getMediaGalleryLayout(media(2))).toBe("pair");
    expect(getMediaGalleryLayout(media(3))).toBe("triple");
    expect(getMediaGalleryLayout(media(4))).toBe("quad");
    expect(getMediaGalleryLayout(media(5))).toBe("overflow");
  });
});

describe("visibleMediaItems", () => {
  it("sorts by position and caps at four", () => {
    const items = visibleMediaItems(media(5));
    expect(items).toHaveLength(4);
    expect(items.map((m) => m.position)).toEqual([1, 2, 3, 4]);
  });
});

describe("usableMediaItems", () => {
  it("drops failed media and recomputes the visible set", () => {
    const items = media(3);
    const failed = [mediaItemKey(items[1]!)];
    const usable = usableMediaItems(items, failed);
    expect(usable).toHaveLength(2);
    expect(usable.map((m) => m.url)).toEqual(["/media/2.jpg", "/media/0.jpg"]);
  });

  it("returns empty when every item failed", () => {
    const items = media(2);
    const failed = items.map(mediaItemKey);
    expect(usableMediaItems(items, failed)).toEqual([]);
  });
});

describe("galleryGridClass", () => {
  it("returns grid classes for non-empty layouts", () => {
    expect(galleryGridClass("empty")).toBe("hidden");
    expect(galleryGridClass("single")).toContain("grid-cols-1");
    expect(galleryGridClass("pair")).toContain("grid-cols-2");
  });
});
