import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DailyReportView } from "@/components/daily/DailyReportView";
import { SiteShell } from "@/components/shared/SiteShell";
import {
  getReport,
  isValidReportDate,
  PublicApiError,
} from "@/lib/api/reports";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ date: string }>;
}

function reportLead(report: { lead?: string; overview: string }): string {
  return (report.lead || report.overview || "").trim();
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { date } = await params;
  if (!isValidReportDate(date)) {
    return { title: "Report not found" };
  }

  try {
    const report = await getReport(date);
    const lead = reportLead(report);
    return {
      title: report.title,
      description: lead.slice(0, 160),
      openGraph: {
        title: report.title,
        description: lead.slice(0, 160),
        type: "article",
        publishedTime: report.published_at ?? undefined,
      },
    };
  } catch {
    return { title: "Report not found" };
  }
}

export default async function DailyReportPage({ params }: PageProps) {
  const { date } = await params;

  if (!isValidReportDate(date)) {
    notFound();
  }

  let report;
  try {
    report = await getReport(date);
  } catch (err) {
    if (err instanceof PublicApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <SiteShell tone="crt">
      <DailyReportView report={report} />
    </SiteShell>
  );
}
