"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { pageTurnToHome } from "@/lib/page-turn";
import { smoothScrollTo } from "@/lib/smooth-scroll";

export function SiteNav() {
  const pathname = usePathname();
  const onHome = pathname === "/";

  return (
    <nav className="site-nav" aria-label="Primary">
      <Link
        href={onHome ? "#home" : "/"}
        className="site-nav-brand group"
        scroll={onHome ? false : undefined}
        onClick={
          onHome
            ? (event) => {
                event.preventDefault();
                const root = document.documentElement;
                if (root.classList.contains("home-report-active")) {
                  pageTurnToHome({ hash: "#home" });
                  return;
                }
                const target = document.getElementById("home");
                if (!target) return;
                smoothScrollTo(target, { hash: "#home", duration: 900 });
              }
            : undefined
        }
      >
        <span className="site-nav-wordmark">Connor</span>
      </Link>
      <div className="site-nav-links">
        <Link href="/about" className="site-nav-link">
          About
        </Link>
      </div>
    </nav>
  );
}
