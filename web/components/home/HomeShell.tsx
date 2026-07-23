"use client";

import { useEffect, type ReactNode } from "react";

import { HomeJumpButton } from "@/components/shared/HomeJumpButton";
import { SiteFooter } from "@/components/shared/SiteFooter";
import { SiteNav } from "@/components/shared/SiteNav";
import { isPageTurning } from "@/lib/page-turn";

interface HomeShellProps {
  children: ReactNode;
}

/**
 * Homepage chrome over the CRT continuum (hero + cobalt report).
 * Nav stays light so it reads on both screens.
 */
export function HomeShell({ children }: HomeShellProps) {
  useEffect(() => {
    const root = document.documentElement;

    if (!window.location.hash || window.location.hash === "#home") {
      window.scrollTo(0, 0);
    }

    let raf = 0;
    let reportActive = root.classList.contains("home-report-active");

    /**
     * Hysteresis avoids flicker/jank at the hero↔report boundary
     * (especially painful when scrolling back up).
     */
    const syncReportActive = () => {
      if (isPageTurning()) return;
      const hero = document.getElementById("home");
      if (!hero) return;
      const bottom = hero.getBoundingClientRect().bottom;
      const vh = window.innerHeight || 1;

      let next = reportActive;
      if (reportActive) {
        // Re-show the CRT as soon as it peeks back in — delaying until ~80%
        // left a blank hero band and made upward scroll feel sticky.
        if (bottom > vh * 0.1) next = false;
      } else {
        // Hide CRT work once the hero is mostly offscreen.
        if (bottom <= vh * 0.3) next = true;
      }

      if (next === reportActive) return;
      reportActive = next;
      root.classList.toggle("home-report-active", reportActive);
    };

    const onScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        syncReportActive();
      });
    };

    syncReportActive();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      root.classList.remove("home-report-active");
    };
  }, []);

  return (
    <div className="home-crt relative flex min-h-screen flex-col">
      <header className="site-header">
        <SiteNav />
      </header>
      <main className="flex-1">{children}</main>
      <HomeJumpButton />
      <SiteFooter tone="crt" />
    </div>
  );
}
