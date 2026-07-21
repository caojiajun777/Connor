import { DigestBody } from "@/components/daily/DigestBody";
import { ReportBody } from "@/components/daily/ReportBody";
import { ReportHeader } from "@/components/daily/ReportHeader";
import { ReportNav } from "@/components/daily/ReportNav";
import { ReportShaderBackdrop } from "@/components/daily/ReportShaderBackdrop";
import type { PublicReportDetail } from "@/lib/types/public";

function reportLead(report: { lead?: string; overview: string }): string {
  return (report.lead || report.overview || "").trim();
}

interface DailyReportViewProps {
  report: PublicReportDetail;
  /** Optional anchor id (e.g. homepage #latest-report). */
  id?: string;
}

export function DailyReportView({ report, id }: DailyReportViewProps) {
  const lead = reportLead(report);
  const digest =
    report.format === "digest_v1" && report.digest?.items?.length
      ? report.digest
      : null;

  return (
    <div id={id} className="report-page-shell home-report-snap scroll-mt-0">
      <ReportShaderBackdrop />
      <article className="report-page">
        <section className="report-hero" aria-label="Report masthead">
          <div className="reading-shell report-surface px-5 py-12 sm:px-8 sm:py-16">
            <ReportHeader
              reportDate={report.report_date}
              title={report.title}
              lead={lead}
              keywords={report.keywords}
              eventCount={
                digest?.items.length ??
                (report.body_sections.length > 0
                  ? report.body_sections.length
                  : null)
              }
              sourceCount={report.source_post_count || report.item_count}
            />
          </div>
        </section>

        <div className="reading-shell report-reading report-surface px-5 py-10 sm:px-8 sm:py-14">
          {digest ? (
            <DigestBody digest={digest} sources={report.items} />
          ) : null}
          {!digest && report.body_sections.length > 0 ? (
            <ReportBody sections={report.body_sections} />
          ) : null}

          <ReportNav
            previousReportDate={report.previous_report_date}
            nextReportDate={report.next_report_date}
          />
        </div>
      </article>
    </div>
  );
}
