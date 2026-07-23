"use client";

import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";

const VISITOR_KEY = "connor_vid";
const SESSION_KEY = "connor_sid";
const OPT_OUT_KEY = "connor_analytics_opt_out";
const OPT_OUT_COOKIE = "connor_analytics_opt_out";
const SESSION_TTL_MS = 30 * 60 * 1000;
const OPT_OUT_MAX_AGE_SEC = 60 * 60 * 24 * 365 * 10; // 10 years

function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return `id_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

/** Local / private hosts are always treated as test traffic (no click needed). */
function isLocalTestHost(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname.toLowerCase();
  return (
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "[::1]" ||
    host === "::1" ||
    host.endsWith(".local")
  );
}

function readCookie(name: string): string | null {
  try {
    const parts = document.cookie.split(";");
    for (const part of parts) {
      const [rawKey, ...rest] = part.trim().split("=");
      if (rawKey === name) return decodeURIComponent(rest.join("=") || "");
    }
  } catch {
    // ignore
  }
  return null;
}

function writeOptOutCookie(enabled: boolean): void {
  try {
    const secure =
      typeof window !== "undefined" && window.location.protocol === "https:"
        ? "; Secure"
        : "";
    if (enabled) {
      document.cookie = `${OPT_OUT_COOKIE}=1; Path=/; Max-Age=${OPT_OUT_MAX_AGE_SEC}; SameSite=Lax${secure}`;
    } else {
      document.cookie = `${OPT_OUT_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax${secure}`;
    }
  } catch {
    // ignore
  }
}

function hasStoredOptOut(): boolean {
  try {
    if (localStorage.getItem(OPT_OUT_KEY) === "1") return true;
  } catch {
    // ignore
  }
  return readCookie(OPT_OUT_COOKIE) === "1";
}

function isBlocked(forceOn: boolean): boolean {
  if (forceOn) return false;
  if (isLocalTestHost()) return true;
  return hasStoredOptOut();
}

function setOptOut(enabled: boolean): void {
  try {
    if (enabled) {
      localStorage.setItem(OPT_OUT_KEY, "1");
    } else {
      localStorage.removeItem(OPT_OUT_KEY);
    }
  } catch {
    // ignore
  }
  writeOptOutCookie(enabled);
}

function readVisitorId(): string {
  try {
    const existing = localStorage.getItem(VISITOR_KEY);
    if (existing && existing.length >= 8) return existing;
    const id = randomId();
    localStorage.setItem(VISITOR_KEY, id);
    return id;
  } catch {
    return randomId();
  }
}

function readSessionId(): string {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { id?: string; at?: number };
      if (
        parsed.id &&
        typeof parsed.at === "number" &&
        Date.now() - parsed.at < SESSION_TTL_MS
      ) {
        sessionStorage.setItem(
          SESSION_KEY,
          JSON.stringify({ id: parsed.id, at: Date.now() }),
        );
        return parsed.id;
      }
    }
    const id = randomId();
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ id, at: Date.now() }));
    return id;
  } catch {
    return randomId();
  }
}

type EventPayload = {
  event_type: "pageview" | "dwell";
  path: string;
  visitor_id: string;
  session_id: string;
  occurred_at?: string;
  dwell_ms?: number;
  referrer?: string | null;
};

function postEvents(
  events: EventPayload[],
  useBeacon: boolean,
  forceOn: boolean,
): void {
  if (!events.length || isBlocked(forceOn)) return;
  const body = JSON.stringify({ events });
  const url = "/api/public/analytics/events";
  if (useBeacon && typeof navigator !== "undefined" && navigator.sendBeacon) {
    try {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon(url, blob)) return;
    } catch {
      // fall through
    }
  }
  void fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}

function stripAnalyticsQuery(): void {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("analytics")) return;
    url.searchParams.delete("analytics");
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(null, "", next);
  } catch {
    // ignore
  }
}

/**
 * Lightweight first-party beacon for Console analytics.
 * - Localhost / 127.0.0.1 never counted (test traffic).
 * - Production owner opt-out: ?analytics=off once (10y cookie + localStorage).
 * - Force-enable locally for debugging: ?analytics=on
 */
export function AnalyticsBeacon() {
  const pathname = usePathname() || "/";
  const searchParams = useSearchParams();
  const pathRef = useRef(pathname);
  const startedAt = useRef(Date.now());
  const ids = useRef<{ visitor: string; session: string } | null>(null);
  const forceOn = useRef(false);

  useEffect(() => {
    const flag = searchParams.get("analytics");
    if (flag === "off" || flag === "0" || flag === "false") {
      setOptOut(true);
      forceOn.current = false;
      stripAnalyticsQuery();
    } else if (flag === "on" || flag === "1" || flag === "true") {
      // Allow local debugging of analytics itself.
      setOptOut(false);
      forceOn.current = true;
      stripAnalyticsQuery();
    } else {
      forceOn.current = false;
    }

    if (isBlocked(forceOn.current)) {
      ids.current = null;
      return;
    }

    ids.current = {
      visitor: readVisitorId(),
      session: readSessionId(),
    };
  }, [searchParams]);

  useEffect(() => {
    if (isBlocked(forceOn.current)) {
      return;
    }

    const flushDwell = (useBeacon: boolean) => {
      if (isBlocked(forceOn.current)) return;
      const idPair = ids.current;
      if (!idPair) return;
      const dwell = Date.now() - startedAt.current;
      if (dwell < 400) return;
      postEvents(
        [
          {
            event_type: "dwell",
            path: pathRef.current,
            visitor_id: idPair.visitor,
            session_id: idPair.session,
            dwell_ms: Math.min(dwell, 86_400_000),
            occurred_at: new Date().toISOString(),
          },
        ],
        useBeacon,
        forceOn.current,
      );
    };

    if (pathRef.current !== pathname) {
      flushDwell(false);
      pathRef.current = pathname;
      startedAt.current = Date.now();
    }

    const idPair = ids.current ?? {
      visitor: readVisitorId(),
      session: readSessionId(),
    };
    ids.current = idPair;

    postEvents(
      [
        {
          event_type: "pageview",
          path: pathname,
          visitor_id: idPair.visitor,
          session_id: idPair.session,
          occurred_at: new Date().toISOString(),
          referrer:
            typeof document !== "undefined" ? document.referrer || null : null,
        },
      ],
      false,
      forceOn.current,
    );

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        flushDwell(true);
      } else if (document.visibilityState === "visible") {
        if (isBlocked(forceOn.current)) return;
        startedAt.current = Date.now();
        ids.current = {
          visitor: readVisitorId(),
          session: readSessionId(),
        };
      }
    };
    const onPageHide = () => flushDwell(true);

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
      flushDwell(true);
    };
  }, [pathname]);

  return null;
}
