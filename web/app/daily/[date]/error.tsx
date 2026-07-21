"use client";

import Link from "next/link";
import { useEffect } from "react";

import { SiteShell } from "@/components/shared/SiteShell";

export default function DailyError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <SiteShell>
      <div className="reading-shell py-28 text-center">
        <h1 className="type-headline text-[40px]">Could not load this report</h1>
        <p className="type-lead mt-3 text-[17px]">
          Something went wrong. Please try again.
        </p>
        <div className="mt-8 flex items-center justify-center gap-4">
          <button type="button" onClick={reset} className="apple-button">
            Retry
          </button>
          <Link href="/archive" className="apple-link text-[15px]">
            Archive
          </Link>
        </div>
      </div>
    </SiteShell>
  );
}
