import type { Metadata } from "next";

import { DailyReportView } from "@/components/daily/DailyReportView";
import { BroadcastHero } from "@/components/home/BroadcastHero";
import { HomeLoadNotice } from "@/components/home/HomeLoadNotice";
import { HomeShell } from "@/components/home/HomeShell";
import { getReport, listReports } from "@/lib/api/reports";
import { extractHeroSlides } from "@/lib/hero-slides";
import type { PublicReportDetail } from "@/lib/types/public";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Connor",
  description: "Daily AI frontier briefings — curated and easy to read.",
};

/** Latest N published days contribute images to the Hero playlist. */
const HERO_REPORT_DAYS = 3;

export default async function HomePage() {
  let items: Awaited<ReturnType<typeof listReports>>["items"] = [];
  let loadFailed = false;

  try {
    const res = await listReports({ limit: HERO_REPORT_DAYS });
    items = res.items;
  } catch {
    loadFailed = true;
    items = [];
  }

  const latest = items.find((i) => i.is_latest) ?? items[0];
  const heroDetails: PublicReportDetail[] = [];

  if (latest) {
    // Newest-first so the reel is 今日 → 昨天 → 前天.
    const recent = [...items]
      .sort((a, b) => b.report_date.localeCompare(a.report_date))
      .slice(0, HERO_REPORT_DAYS);

    const detailResults = await Promise.all(
      recent.map(async (item) => {
        try {
          return await getReport(item.report_date);
        } catch {
          return null;
        }
      }),
    );

    for (const detail of detailResults) {
      if (detail) heroDetails.push(detail);
    }
  }

  const slides = extractHeroSlides(heroDetails, { maxSlides: 9 });
  const latestReport =
    (latest &&
      heroDetails.find((d) => d.report_date === latest.report_date)) ||
    null;

  return (
    <HomeShell>
      <section
        id="home"
        className="home-crt home-panel--hero"
        aria-label="Connor home"
      >
        <BroadcastHero
          slides={slides}
          latestHref={latestReport ? "#latest-report" : null}
        />
      </section>

      {latestReport ? (
        <section className="home-panel--report" aria-label="Today's briefing">
          <DailyReportView report={latestReport} id="latest-report" />
        </section>
      ) : (
        <HomeLoadNotice variant={loadFailed ? "error" : "empty"} />
      )}
    </HomeShell>
  );
}
