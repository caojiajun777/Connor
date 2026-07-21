import { MediaGallery } from "@/components/daily/MediaGallery";
import { EvidenceBlock } from "@/components/daily/EvidenceBlock";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import {
  padRank,
  postIdFromUrl,
  summarizeHandles,
} from "@/lib/format";
import type {
  PublicDigestDocument,
  PublicDigestNewsItem,
  PublicMediaItem,
  PublicReportItem,
} from "@/lib/types/public";

interface DigestBodyProps {
  digest: PublicDigestDocument;
  sources?: PublicReportItem[];
}

function toGalleryMedia(
  images: PublicDigestNewsItem["images"],
): PublicMediaItem[] {
  return images.map((img, index) => ({
    type: img.type || "image",
    url: img.url,
    width: img.width,
    height: img.height,
    alt_text: img.alt_text,
    position: img.position ?? index,
  }));
}

function resolveSources(
  item: PublicDigestNewsItem,
  catalog: PublicReportItem[],
): PublicReportItem[] {
  const cite = new Set(item.citation_post_ids.map(String));
  const linkSet = new Set(item.links);
  if (cite.size === 0 && linkSet.size === 0) return [];

  return catalog.filter((row) => {
    const url = row.post.original_url || "";
    const id = postIdFromUrl(url);
    if (id && cite.has(id)) return true;
    if (linkSet.has(url)) return true;
    return false;
  });
}

function isCompact(item: PublicDigestNewsItem): boolean {
  const paragraphs = item.body.split(/\n+/).filter(Boolean);
  return paragraphs.length <= 2 && item.images.length === 0 && !item.blurb;
}

function DigestArticle({
  item,
  sources,
  variant,
}: {
  item: PublicDigestNewsItem;
  sources: PublicReportItem[];
  variant: "lead" | "signal" | "compact";
}) {
  const matched = resolveSources(item, sources);
  const sourceCount = Math.max(item.citation_post_ids.length, matched.length);
  const handles = matched.map((s) => s.post.author_handle);
  const handleSummary = summarizeHandles(handles);
  const compact = variant === "compact" || isCompact(item);
  const titleSize =
    variant === "lead"
      ? "text-[26px] sm:text-[34px]"
      : compact
        ? "text-[20px] sm:text-[24px]"
        : "text-[22px] sm:text-[28px]";

  return (
    <article
      id={`digest-${item.rank}`}
      className={`scroll-mt-28 ${
        variant === "lead" ? "pb-10 sm:pb-12" : compact ? "py-6" : "py-8 sm:py-9"
      }`}
    >
      <h2 className={`type-headline ${titleSize}`}>{item.headline}</h2>

      {item.blurb && variant === "lead" ? (
        <p className="type-lead mt-3 max-w-[40rem] text-[17px] sm:text-[19px]">
          {item.blurb}
        </p>
      ) : item.blurb ? (
        <p className="mt-2 text-[15px] leading-relaxed text-text-secondary sm:text-[16px]">
          {item.blurb}
        </p>
      ) : null}

      {item.images.length > 0 ? (
        <div className={variant === "lead" ? "mt-6" : "mt-5"}>
          <MediaGallery
            media={toGalleryMedia(item.images)}
            variant="article"
          />
        </div>
      ) : null}

      <div className={`space-y-3 ${variant === "lead" ? "mt-5" : "mt-4"}`}>
        {item.body
          .split(/\n+/)
          .filter(Boolean)
          .map((paragraph, pIndex) => (
            <p
              key={`${item.rank}-p-${pIndex}`}
              className={`type-body ${
                compact ? "text-[16px] sm:text-[17px]" : "text-[17px] sm:text-[19px]"
              }`}
            >
              {paragraph}
            </p>
          ))}
      </div>

      <EvidenceBlock
        sourceCount={sourceCount}
        handleSummary={handleSummary}
        sources={matched}
        links={item.links}
      />
    </article>
  );
}

export function DigestBody({ digest, sources = [] }: DigestBodyProps) {
  if (!digest.items.length) {
    return null;
  }

  const [lead, ...rest] = [...digest.items].sort((a, b) => a.rank - b.rank);

  return (
    <div className="mx-auto max-w-[720px]">
      {digest.toc.length > 0 ? (
        <nav
          aria-label="Today’s Index"
          className="digest-index mb-10 py-5 sm:mb-12 sm:py-6"
        >
          <SignalMarker className="mb-3">
            <SignalMeta as="span" className="type-signal-accent">
              Today&apos;s Index
            </SignalMeta>
          </SignalMarker>
          <div className="space-y-4">
            {digest.toc.map((section) => (
              <div key={section.category}>
                <p className="type-signal mb-1.5">{section.category}</p>
                <ol className="space-y-1.5">
                  {section.entries.map((entry) => (
                    <li key={`${section.category}-${entry.rank}`}>
                      <a
                        href={`#digest-${entry.rank}`}
                        className="toc-link group flex gap-3 text-[14px] leading-snug text-text-secondary sm:text-[15px]"
                      >
                        <span className="shrink-0 font-mono text-[11px] tabular-nums tracking-wider text-muted">
                          {padRank(entry.rank)}
                        </span>
                        <span className="group-hover:underline group-hover:underline-offset-4">
                          {entry.headline}
                        </span>
                      </a>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </nav>
      ) : null}

      <section aria-labelledby="lead-story-label">
        <SignalMarker className="mb-4">
          <SignalMeta id="lead-story-label" as="span" className="type-signal-accent">
            Lead Story
          </SignalMeta>
        </SignalMarker>
        <DigestArticle item={lead} sources={sources} variant="lead" />
      </section>

      {rest.length > 0 ? (
        <section aria-labelledby="key-signals-label" className="hairline-y pt-8 sm:pt-10">
          <SignalMarker className="mb-2">
            <SignalMeta
              id="key-signals-label"
              as="span"
              className="type-signal-accent"
            >
              Key Signals
            </SignalMeta>
          </SignalMarker>
          <div className="divide-y divide-[var(--hairline)]">
            {rest.map((item) => (
              <DigestArticle
                key={item.event_id || item.rank}
                item={item}
                sources={sources}
                variant={isCompact(item) ? "compact" : "signal"}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
