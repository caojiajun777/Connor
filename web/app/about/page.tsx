import type { Metadata } from "next";

import { Reveal } from "@/components/shared/Reveal";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import { SiteShell } from "@/components/shared/SiteShell";
import { padRank } from "@/lib/format";

export const metadata: Metadata = {
  title: "About",
  description: "Principles behind Connor public briefings.",
};

const principles = [
  {
    title: "Signal over spectacle",
    body: "Connor surfaces a small set of public posts that matter for operators tracking the AI frontier — not a firehose, not a feed.",
  },
  {
    title: "Primary sources preserved",
    body: "Every item keeps author attribution, timestamps, and a link back to the original post when it remains publicly available.",
  },
  {
    title: "Narrative, then sources",
    body: "The briefing is written from packaged events — title, lead, and layered body. Faithful translations stay on source cards for verification, not as the article itself.",
  },
  {
    title: "Editorial restraint",
    body: "Reports are curated and published deliberately. Withdrawals and unavailable sources are marked clearly instead of silently rewritten.",
  },
];

export default function AboutPage() {
  return (
    <SiteShell>
      <section className="hero-panel">
        <div className="reading-shell pt-28 pb-20 text-center sm:pt-32 sm:pb-28">
          <div className="anim-soft-rise flex justify-center">
            <SignalMarker>
              <SignalMeta as="span" className="type-signal-accent">
                About
              </SignalMeta>
            </SignalMarker>
          </div>
          <h1 className="type-hero anim-soft-rise delay-1 mt-4 text-[48px] sm:text-[56px]">
            About Connor
          </h1>
          <p className="type-lead-italic anim-soft-rise delay-2 mx-auto mt-4 max-w-[620px] text-[19px] sm:text-[21px]">
            面向 AI 前沿的公开日报。
            <span className="text-text-tertiary">冷静阅读，清晰出处。</span>
          </p>
        </div>
      </section>

      <section className="reading-shell py-16 sm:py-24">
        <div className="mx-auto max-w-[720px]">
          <SignalMarker className="mb-8">
            <SignalMeta as="span">Principles</SignalMeta>
          </SignalMarker>
          <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
            {principles.map((p, index) => (
              <Reveal
                key={p.title}
                soft
                delayMs={index * 60}
                as="article"
                className="grid gap-4 py-8 sm:grid-cols-[4.5rem_1fr] sm:gap-8 sm:py-10"
              >
                <SignalMeta
                  as="p"
                  className="type-signal-accent pt-1 text-[13px] tracking-[0.14em]"
                >
                  {padRank(index + 1)}
                </SignalMeta>
                <div>
                  <h2 className="type-headline text-[22px] sm:text-[26px]">
                    {p.title}
                  </h2>
                  <p className="type-body mt-3 text-[16px] text-text-secondary sm:text-[17px]">
                    {p.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>
    </SiteShell>
  );
}
