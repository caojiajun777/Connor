"use client";

import type { MouseEvent } from "react";

import { padRank } from "@/lib/format";
import { smoothScrollTo } from "@/lib/smooth-scroll";

type DigestTocLinkProps = {
  rank: number;
  headline: string;
};

/**
 * Index → digest jump. Native hash scroll is wrong on first click because
 * images above the target still loading shift the page after landing.
 */
export function DigestTocLink({ rank, headline }: DigestTocLinkProps) {
  const hash = `#digest-${rank}`;

  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const target = document.getElementById(`digest-${rank}`);
    if (!target) return;
    event.preventDefault();
    smoothScrollTo(target, {
      hash,
      offset: "header",
      duration: 720,
      settle: true,
    });
  };

  return (
    <a
      href={hash}
      onClick={onClick}
      className="toc-link group flex gap-3 text-[14px] leading-snug text-text-secondary sm:text-[15px]"
    >
      <span className="shrink-0 font-mono text-[11px] tabular-nums tracking-wider text-muted">
        {padRank(rank)}
      </span>
      <span className="group-hover:underline group-hover:underline-offset-4">
        {headline}
      </span>
    </a>
  );
}
