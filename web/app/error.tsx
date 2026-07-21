"use client";

import Link from "next/link";
import { useEffect } from "react";

import { SiteShell } from "@/components/shared/SiteShell";

export default function AppError({
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
        <p className="type-signal type-signal-accent">Error</p>
        <h1 className="type-headline mt-3 text-[36px] sm:text-[44px]">
          Something went wrong
        </h1>
        <p className="mt-3 text-[17px] text-text-secondary">
          Please try again, or return to the archive.
        </p>
        <div className="mt-8 flex items-center justify-center gap-4">
          <button type="button" onClick={reset} className="apple-button">
            Retry
          </button>
          <Link href="/" className="apple-link text-[15px]">
            Home
          </Link>
        </div>
      </div>
    </SiteShell>
  );
}
