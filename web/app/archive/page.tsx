import type { Metadata } from "next";

import { ArchiveEmpty } from "@/components/archive/ArchiveEmpty";
import { ArchiveError } from "@/components/archive/ArchiveError";
import { ArchiveTimeline } from "@/components/archive/ArchiveTimeline";
import { Reveal } from "@/components/shared/Reveal";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import { SiteShell } from "@/components/shared/SiteShell";
import { listReports } from "@/lib/api/reports";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Archive · Connor",
  description: "Published Connor daily briefings, by date.",
};

export default async function ArchivePage() {
  let error: string | null = null;
  let items: Awaited<ReturnType<typeof listReports>>["items"] = [];

  try {
    const res = await listReports({ limit: 365 });
    items = res.items;
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load archive";
  }

  return (
    <SiteShell tone="crt">
      <section className="home-archive reading-shell scroll-mt-16 pt-24 pb-16 sm:pt-28 sm:pb-24">
        <Reveal soft className="mb-10 max-w-[680px]">
          <SignalMarker className="mb-3">
            <SignalMeta as="span">Archive</SignalMeta>
          </SignalMarker>
          <h1 className="type-headline mt-2 text-[32px] sm:text-[40px]">
            往期日报
          </h1>
        </Reveal>

        {error ? (
          <ArchiveError />
        ) : items.length === 0 ? (
          <ArchiveEmpty />
        ) : (
          <ArchiveTimeline items={items} />
        )}
      </section>
    </SiteShell>
  );
}
