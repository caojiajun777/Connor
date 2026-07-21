"use client";

import { useEffect, type ReactNode } from "react";

import { SiteFooter } from "@/components/shared/SiteFooter";
import { SiteNav } from "@/components/shared/SiteNav";

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
    root.classList.add("home-snap-root");

    if (!window.location.hash || window.location.hash === "#home") {
      window.scrollTo(0, 0);
    }

    return () => root.classList.remove("home-snap-root");
  }, []);

  return (
    <div className="home-crt relative flex min-h-screen flex-col">
      <header className="site-header">
        <SiteNav />
      </header>
      <main className="flex-1">{children}</main>
      <SiteFooter tone="crt" />
    </div>
  );
}
