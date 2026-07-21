"use client";

import { useId, useState } from "react";

import { PostCard } from "@/components/daily/PostCard";
import { safeHttpUrl } from "@/lib/safe-url";
import type { PublicReportItem } from "@/lib/types/public";

type EvidenceBlockProps = {
  sourceCount: number;
  handleSummary: string;
  sources: PublicReportItem[];
  links: string[];
};

export function EvidenceBlock({
  sourceCount,
  handleSummary,
  sources,
  links,
}: EvidenceBlockProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const safeLinks = links
    .map((url) => safeHttpUrl(url))
    .filter((url): url is string => Boolean(url));

  if (sourceCount <= 0 && sources.length === 0 && safeLinks.length === 0) {
    return null;
  }

  const countLabel = `${
    Math.max(sourceCount, sources.length) || safeLinks.length
  } SOURCES`;
  const summaryParts = [countLabel];
  if (handleSummary) summaryParts.push(handleSummary);

  return (
    <div className="mt-5">
      <div className="evidence-summary flex flex-wrap items-center gap-x-2 gap-y-1">
        <span>{summaryParts.join(" · ")}</span>
        <span aria-hidden>·</span>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide evidence" : "View evidence"}
        </button>
      </div>

      {open ? (
        <div id={panelId} className="mt-4 space-y-4">
          {sources.length > 0
            ? sources.map((item) => (
                <PostCard
                  key={`${item.display_order}-${item.post.original_url}`}
                  item={item}
                />
              ))
            : null}
          {sources.length === 0 && safeLinks.length > 0 ? (
            <ul className="space-y-2 rounded-[var(--radius-sm)] bg-surface-secondary p-4">
              {safeLinks.map((url) => (
                <li key={url}>
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-[13px] text-text-secondary underline underline-offset-4 transition-colors hover:text-text-primary"
                  >
                    {url}
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
