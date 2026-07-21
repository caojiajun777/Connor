import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { Reveal } from "@/components/shared/Reveal";

interface ReportNavProps {
  previousReportDate: string | null;
  nextReportDate: string | null;
}

export function ReportNav({
  previousReportDate,
  nextReportDate,
}: ReportNavProps) {
  return (
    <Reveal
      as="nav"
      soft
      className="mt-16 flex items-center justify-between border-t border-[var(--hairline)] pt-8"
      aria-label="Report navigation"
      delayMs={60}
    >
      {previousReportDate ? (
        <Link
          href={`/daily/${previousReportDate}`}
          className="apple-link inline-flex items-center gap-1 text-[14px] italic"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
          Previous
        </Link>
      ) : (
        <span />
      )}
      <Link
        href="/archive"
        className="text-[14px] italic text-text-tertiary transition-colors duration-200 hover:text-accent"
      >
        Archive
      </Link>
      {nextReportDate ? (
        <Link
          href={`/daily/${nextReportDate}`}
          className="apple-link inline-flex items-center gap-1 text-[14px] italic"
        >
          Next
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Link>
      ) : (
        <span />
      )}
    </Reveal>
  );
}
