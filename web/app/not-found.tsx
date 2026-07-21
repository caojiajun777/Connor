import Link from "next/link";

import { SiteShell } from "@/components/shared/SiteShell";

export default function NotFound() {
  return (
    <SiteShell>
      <div className="reading-shell py-28 text-center">
        <p className="type-signal type-signal-accent">404</p>
        <h1 className="type-headline mt-3 text-[36px] sm:text-[44px]">
          Page not found
        </h1>
        <p className="mt-3 text-[17px] text-text-secondary">
          This route does not exist in the public archive.
        </p>
        <div className="mt-8">
          <Link href="/" className="apple-button">
            Back to Connor
          </Link>
        </div>
      </div>
    </SiteShell>
  );
}
