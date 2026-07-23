"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { pageTurnToHome } from "@/lib/page-turn";

/**
 * Always-on escape hatch back to the hero / home while reading a daily.
 * Hidden only while the homepage hero already fills the viewport.
 */
export function HomeJumpButton() {
  const pathname = usePathname();
  const onHome = pathname === "/";
  const [visible, setVisible] = useState(!onHome);

  useEffect(() => {
    if (!onHome) {
      setVisible(true);
      return;
    }

    let raf = 0;
    const sync = () => {
      const hero = document.getElementById("home");
      if (!hero) {
        setVisible(true);
        return;
      }
      // Show once the report (or anything below hero) is the reading surface.
      setVisible(hero.getBoundingClientRect().bottom <= window.innerHeight * 0.55);
    };

    const onScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        sync();
      });
    };

    sync();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [onHome]);

  if (!visible) return null;

  return (
    <Link
      href={onHome ? "#home" : "/"}
      className="home-jump-button"
      scroll={onHome ? false : undefined}
      aria-label="回到首页"
      onClick={
        onHome
          ? (event) => {
              event.preventDefault();
              pageTurnToHome({ hash: "#home" });
            }
          : undefined
      }
    >
      首页
    </Link>
  );
}
