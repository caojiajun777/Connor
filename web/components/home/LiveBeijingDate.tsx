"use client";

import { useEffect, useState } from "react";

/** "Jul 22, 2026" in Asia/Shanghai — matches formatReportDate style. */
export function formatBeijingDate(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(now);
}

type LiveBeijingDateProps = {
  className?: string;
};

/**
 * Live calendar day for the Hero — updates across midnight Beijing time
 * without waiting for a report publish or full page reload.
 */
export function LiveBeijingDate({ className }: LiveBeijingDateProps) {
  const [label, setLabel] = useState(() => formatBeijingDate());

  useEffect(() => {
    const sync = () => setLabel(formatBeijingDate());
    sync();

    const interval = window.setInterval(sync, 30_000);

    // Align a one-shot refresh just after Beijing midnight.
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Shanghai",
      hour: "numeric",
      minute: "numeric",
      second: "numeric",
      hourCycle: "h23",
    }).formatToParts(new Date());
    const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
    const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
    const second = Number(parts.find((p) => p.type === "second")?.value ?? 0);
    const msUntilMidnight =
      ((24 * 60 * 60 - (hour * 3600 + minute * 60 + second)) % (24 * 60 * 60)) *
        1000 +
      1500;
    const midnight = window.setTimeout(sync, msUntilMidnight);

    return () => {
      window.clearInterval(interval);
      window.clearTimeout(midnight);
    };
  }, []);

  return (
    <p className={className} suppressHydrationWarning>
      {label}
    </p>
  );
}
