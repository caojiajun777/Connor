"use client";

import Image from "next/image";
import { useCallback, useMemo, useState } from "react";

import {
  galleryGridClass,
  getMediaGalleryLayout,
  mediaItemKey,
  usableMediaItems,
} from "@/lib/media-gallery";
import type { PublicMediaItem } from "@/lib/types/public";

interface MediaGalleryProps {
  media: PublicMediaItem[];
  /** grid = tweet-style crop grids; article = natural aspect for digest body */
  variant?: "grid" | "article";
}

function ArticleImage({
  item,
  onError,
}: {
  item: PublicMediaItem;
  onError: () => void;
}) {
  const hasSize =
    typeof item.width === "number" &&
    item.width > 0 &&
    typeof item.height === "number" &&
    item.height > 0;

  return (
    <figure className="media-frame media-frame-article m-0 block w-full overflow-hidden rounded-[18px] bg-[#f0f0f2]">
      {item.type === "video" ? (
        <video
          src={item.url}
          className="mx-auto h-auto max-h-[min(72vh,720px)] w-full object-contain"
          muted
          playsInline
          preload="metadata"
          controls={false}
          onError={onError}
        />
      ) : hasSize ? (
        <Image
          src={item.url}
          alt={item.alt_text ?? "Post media"}
          width={item.width!}
          height={item.height!}
          className="mx-auto h-auto max-h-[min(72vh,720px)] w-full object-contain"
          sizes="(max-width: 768px) 100vw, 720px"
          quality={95}
          unoptimized
          draggable={false}
          onError={onError}
        />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.url}
          alt={item.alt_text ?? "Post media"}
          className="mx-auto h-auto max-h-[min(72vh,720px)] w-full object-contain"
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={onError}
        />
      )}
    </figure>
  );
}

export function MediaGallery({ media, variant = "grid" }: MediaGalleryProps) {
  const [failedKeys, setFailedKeys] = useState<Set<string>>(() => new Set());

  const maxItems = variant === "article" ? 3 : 4;
  const items = useMemo(
    () => usableMediaItems(media, failedKeys, maxItems),
    [media, failedKeys, maxItems],
  );
  const layout = getMediaGalleryLayout(items);

  const markFailed = useCallback((item: PublicMediaItem) => {
    const key = mediaItemKey(item);
    setFailedKeys((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }, []);

  if (layout === "empty" || items.length === 0) return null;

  if (variant === "article") {
    return (
      <div className="space-y-3">
        {items.map((item) => (
          <ArticleImage
            key={mediaItemKey(item)}
            item={item}
            onError={() => markFailed(item)}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className={`mt-5 overflow-hidden rounded-[18px] bg-white ${galleryGridClass(layout)}`}
    >
      {items.map((item, i) => {
        const isTallTriple = layout === "triple" && i === 0;
        return (
          <div
            key={mediaItemKey(item)}
            className={`media-frame relative bg-surface-secondary ${
              isTallTriple ? "row-span-2 min-h-[220px]" : "min-h-[140px]"
            } ${layout === "single" ? "aspect-[16/10] min-h-[200px]" : ""}`}
          >
            {item.type === "video" ? (
              <video
                src={item.url}
                className="h-full w-full object-cover"
                muted
                playsInline
                preload="metadata"
                controls={false}
                onError={() => markFailed(item)}
              />
            ) : (
              <Image
                src={item.url}
                alt={item.alt_text ?? "Post media"}
                fill
                className="object-cover"
                sizes="(max-width: 768px) 100vw, 560px"
                quality={90}
                unoptimized
                draggable={false}
                onError={() => markFailed(item)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
