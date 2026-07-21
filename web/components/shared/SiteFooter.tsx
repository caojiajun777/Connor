import Image from "next/image";
import Link from "next/link";

import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";

interface SiteFooterProps {
  tone?: "default" | "crt";
}

export function SiteFooter({ tone = "default" }: SiteFooterProps) {
  const isCrt = tone === "crt";

  return (
    <footer
      className={[
        "mt-auto border-t",
        isCrt
          ? "border-[var(--hairline)] bg-[rgba(4,12,46,0.72)]"
          : "border-[var(--hairline)] bg-surface-secondary/80",
      ].join(" ")}
    >
      <div
        className={[
          "reading-shell py-10 text-[12px] leading-5",
          isCrt ? "text-[var(--text-tertiary)]" : "text-text-tertiary",
        ].join(" ")}
      >
        <div className="flex flex-col gap-4 border-b border-[var(--hairline)] pb-6 sm:flex-row sm:items-center sm:justify-between">
          <SignalMarker>
            <span className="inline-flex items-center gap-2">
              <Image
                src={isCrt ? "/connor-mark-light.png" : "/connor-mark.png"}
                alt=""
                width={18}
                height={18}
                className="h-[18px] w-[18px] object-contain"
                unoptimized
              />
              <span
                className={[
                  "font-display text-[14px] font-semibold tracking-[-0.02em]",
                  isCrt ? "text-[var(--crt-ink,#eef4ff)]" : "text-ink-soft",
                ].join(" ")}
              >
                Connor
              </span>
            </span>
          </SignalMarker>
          <div className="flex gap-6">
            <Link
              href="/archive"
              className="type-signal transition-colors duration-200 hover:text-text-secondary"
            >
              Archive
            </Link>
            <Link
              href="/about"
              className="type-signal transition-colors duration-200 hover:text-text-secondary"
            >
              About
            </Link>
          </div>
        </div>
        <SignalMeta as="p" className="pt-5 text-text-quaternary">
          Copyright {new Date().getFullYear()} · Frontier intelligence
        </SignalMeta>
      </div>
    </footer>
  );
}
