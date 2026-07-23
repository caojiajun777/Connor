import { KeywordChips } from "@/components/shared/KeywordChips";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import { displayReportTitle, formatReportDateLong } from "@/lib/format";

interface ReportHeaderProps {
  reportDate: string;
  title: string;
  lead: string;
  keywords: string[];
  eventCount?: number | null;
  sourceCount?: number | null;
}

export function ReportHeader({
  reportDate,
  title,
  lead,
  keywords,
  eventCount,
  sourceCount,
}: ReportHeaderProps) {
  const metaBits: string[] = [formatReportDateLong(reportDate)];
  if (typeof eventCount === "number" && eventCount > 0) {
    metaBits.push(
      `${eventCount} ${eventCount === 1 ? "EVENT" : "EVENTS"}`,
    );
  }
  if (typeof sourceCount === "number" && sourceCount > 0) {
    metaBits.push(
      `${sourceCount} ${sourceCount === 1 ? "SOURCE" : "SOURCES"}`,
    );
  }

  return (
    <header className="report-header pb-2 text-center sm:pb-4">
      <div className="anim-soft-rise flex justify-center">
        <SignalMarker>
          <SignalMeta as="span" className="type-signal-accent">
            Daily Briefing
          </SignalMeta>
        </SignalMarker>
      </div>
      <time
        dateTime={reportDate}
        className="type-signal anim-soft-rise delay-1 mt-4 block"
      >
        {metaBits.join(" · ")}
      </time>
      <h1 className="type-headline anim-soft-rise delay-2 mx-auto mt-5 max-w-[820px] text-[34px] sm:text-[48px]">
        {displayReportTitle(title)}
      </h1>
      {lead ? (
        <p className="type-lead-italic anim-soft-rise delay-3 mx-auto mt-5 max-w-[680px] text-[17px] sm:text-[19px]">
          {lead}
        </p>
      ) : null}
      {keywords.length > 0 ? (
        <div className="anim-soft-rise delay-4 mt-6 flex flex-col items-center gap-3">
          <KeywordChips keywords={keywords} />
        </div>
      ) : null}
    </header>
  );
}
