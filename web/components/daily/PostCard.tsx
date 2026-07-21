import { ExternalLink } from "lucide-react";
import Image from "next/image";

import { MediaGallery } from "@/components/daily/MediaGallery";
import { TranslationBlock } from "@/components/daily/TranslationBlock";
import { formatPostedAt, initialsFromName } from "@/lib/format";
import { safeHttpUrl } from "@/lib/safe-url";
import type { PublicReportItem } from "@/lib/types/public";

interface PostCardProps {
  item: PublicReportItem;
}

export function PostCard({ item }: PostCardProps) {
  const { post, category } = item;
  const handle = post.author_handle.replace(/^@/, "");
  const originalUrl = safeHttpUrl(post.original_url);
  const avatarUrl = safeHttpUrl(post.author_avatar_url);

  return (
    <article className="apple-tile apple-tile-interactive p-6 sm:p-8">
      <header className="flex items-start gap-3">
        <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full bg-surface ring-1 ring-[var(--hairline)]">
          {avatarUrl ? (
            <Image
              src={avatarUrl}
              alt=""
              fill
              className="object-cover"
              sizes="44px"
              unoptimized
            />
          ) : (
            <span className="flex h-full w-full items-center justify-center text-[12px] font-semibold text-text-secondary">
              {initialsFromName(post.author_name || handle)}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="truncate text-[15px] font-semibold tracking-[-0.016em] text-text-primary">
              {post.author_name || handle}
            </span>
            <span className="truncate text-[14px] italic tracking-[-0.01em] text-text-tertiary">
              @{handle}
            </span>
          </div>
          <time
            dateTime={post.posted_at}
            className="type-caption mt-0.5 block text-[12px]"
          >
            {formatPostedAt(post.posted_at)}
          </time>
        </div>
        {category ? (
          <span className="chip shrink-0">{category}</span>
        ) : null}
      </header>

      {post.unavailable ? (
        <div className="mt-5 rounded-[18px] bg-surface px-5 py-5 ring-1 ring-[var(--hairline)]">
          <p className="type-lead-italic text-[15px]">
            This source is no longer publicly available.
          </p>
        </div>
      ) : (
        <>
          {post.text_original ? (
            <p className="type-body mt-5 whitespace-pre-wrap text-[17px] text-text-primary sm:text-[19px]">
              {post.text_original}
            </p>
          ) : null}
          <MediaGallery media={post.media} />
          <TranslationBlock text={post.text_translated} />
        </>
      )}

      {originalUrl ? (
        <div className="mt-5">
          <a
            href={originalUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="apple-link inline-flex items-center gap-1.5 text-[14px] italic"
          >
            View original
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>
      ) : null}
    </article>
  );
}
