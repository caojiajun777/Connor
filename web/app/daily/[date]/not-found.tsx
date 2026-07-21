import Link from "next/link";

import { SiteShell } from "@/components/shared/SiteShell";

export default function DailyNotFound() {
  return (
    <SiteShell>
      <div className="reading-shell py-28 text-center">
        <h1 className="type-headline text-[40px]">Report not found</h1>
        <p className="type-lead mt-3 text-[17px]">
          This date has no published briefing, or the link is invalid.
        </p>
        <Link href="/archive" className="apple-button mt-8 inline-flex">
          Back to archive
        </Link>
      </div>
    </SiteShell>
  );
}
