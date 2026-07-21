import Link from "next/link";

import { Reveal } from "@/components/shared/Reveal";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import { formatReportDate, monthLabel } from "@/lib/format";
import type { PublicReportListItem } from "@/lib/types/public";

interface ArchiveTimelineProps {
  items: PublicReportListItem[];
}

interface MonthGroup {
  key: string;
  year: number;
  month: number;
  items: PublicReportListItem[];
}

function groupByMonth(items: PublicReportListItem[]): MonthGroup[] {
  const map = new Map<string, MonthGroup>();

  for (const item of items) {
    const [y, m] = item.report_date.split("-").map(Number);
    const key = `${y}-${String(m).padStart(2, "0")}`;
    let group = map.get(key);
    if (!group) {
      group = { key, year: y, month: m, items: [] };
      map.set(key, group);
    }
    group.items.push(item);
  }

  return Array.from(map.values()).sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    return b.month - a.month;
  });
}

export function ArchiveTimeline({ items }: ArchiveTimelineProps) {
  const groups = groupByMonth(items);
  const years = Array.from(new Set(groups.map((g) => g.year))).sort(
    (a, b) => b - a,
  );

  return (
    <div className="space-y-16">
      {years.map((year, yearIndex) => {
        const yearGroups = groups.filter((g) => g.year === year);
        return (
          <Reveal
            key={year}
            as="section"
            soft
            delayMs={yearIndex * 40}
            aria-labelledby={`year-${year}`}
          >
            <div className="mb-6 flex items-baseline gap-3 border-b border-[var(--hairline)] pb-3">
              <h3
                id={`year-${year}`}
                className="type-headline text-[36px] sm:text-[44px]"
              >
                {year}
              </h3>
              <SignalMeta as="span">
                {yearGroups.reduce((n, g) => n + g.items.length, 0)} ISSUES
              </SignalMeta>
            </div>

            <div className="space-y-10">
              {yearGroups.map((group) => (
                <div key={group.key}>
                  <SignalMarker className="mb-3">
                    <SignalMeta as="span">
                      {monthLabel(group.year, group.month)}
                    </SignalMeta>
                  </SignalMarker>

                  <ul className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
                    {group.items.map((item) => (
                      <li key={item.report_date}>
                        <Link
                          href={`/daily/${item.report_date}`}
                          className="apple-row group flex flex-col gap-2 py-5 sm:flex-row sm:items-baseline sm:gap-8 sm:py-6"
                        >
                          <div className="shrink-0 sm:w-36">
                            <time
                              dateTime={item.report_date}
                              className="type-signal block"
                            >
                              {formatReportDate(item.report_date)}
                            </time>
                            {item.is_latest ? (
                              <span className="type-signal type-signal-accent mt-1.5 block">
                                Latest
                              </span>
                            ) : null}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="type-headline text-[20px] transition-colors duration-200 group-hover:text-accent sm:text-[22px]">
                              {item.title}
                            </p>
                            {item.overview_excerpt ? (
                              <p className="type-lead-italic mt-2 line-clamp-2 text-[15px]">
                                {item.overview_excerpt}
                              </p>
                            ) : null}
                            <SignalMeta as="p" className="mt-2">
                              {item.item_count}{" "}
                              {item.item_count === 1 ? "SOURCE" : "SOURCES"}
                            </SignalMeta>
                          </div>
                          <span
                            aria-hidden
                            className="row-chevron hidden text-[22px] font-light text-accent sm:block"
                          >
                            ›
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Reveal>
        );
      })}
    </div>
  );
}
