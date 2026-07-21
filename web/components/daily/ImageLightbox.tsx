"use client";

import { X } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect } from "react";

import { mediaItemKey } from "@/lib/media-gallery";
import type { PublicMediaItem } from "@/lib/types/public";

interface ImageLightboxProps {
  media: PublicMediaItem[];
  index: number;
  open: boolean;
  onClose: () => void;
  onIndexChange: (index: number) => void;
  onMediaError?: (item: PublicMediaItem) => void;
}

export function ImageLightbox({
  media,
  index,
  open,
  onClose,
  onIndexChange,
  onMediaError,
}: ImageLightboxProps) {
  const count = media.length;
  const current = media[index];

  const go = useCallback(
    (delta: number) => {
      if (count <= 0) return;
      const next = (index + delta + count) % count;
      onIndexChange(next);
    },
    [count, index, onIndexChange],
  );

  useEffect(() => {
    if (!open) return;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") go(-1);
      if (e.key === "ArrowRight") go(1);
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, go]);

  useEffect(() => {
    if (open && count === 0) onClose();
  }, [open, count, onClose]);

  if (!open || !current) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface-dark/92 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Media lightbox"
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute right-4 top-4 rounded-small border border-white/20 p-2 text-text-inverse hover:bg-white/10"
        aria-label="Close"
      >
        <X className="h-5 w-5" />
      </button>

      <div
        className="relative flex max-h-[85vh] max-w-5xl flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative h-[70vh] w-[min(92vw,900px)]">
          {current.type === "video" ? (
            <video
              key={mediaItemKey(current)}
              src={current.url}
              controls
              className="h-full w-full object-contain"
              onError={() => onMediaError?.(current)}
            />
          ) : (
            <Image
              key={mediaItemKey(current)}
              src={current.url}
              alt={current.alt_text ?? "Media"}
              fill
              className="object-contain"
              sizes="100vw"
              quality={95}
              unoptimized
              onError={() => onMediaError?.(current)}
            />
          )}
        </div>

        <div className="mt-4 flex items-center gap-6 font-mono text-xs tracking-[0.12em] text-text-inverse/80">
          {count > 1 ? (
            <button
              type="button"
              onClick={() => go(-1)}
              className="hover:text-accent"
            >
              ← PREV
            </button>
          ) : null}
          <span>
            {index + 1} / {count}
          </span>
          {count > 1 ? (
            <button
              type="button"
              onClick={() => go(1)}
              className="hover:text-accent"
            >
              NEXT →
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
