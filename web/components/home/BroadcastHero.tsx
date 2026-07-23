"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { padRank } from "@/lib/format";
import type { HeroSlide } from "@/lib/hero-slides";
import { pageTurnToReport } from "@/lib/page-turn";
import { LiveBeijingDate } from "@/components/home/LiveBeijingDate";

const HOLD_MS = 6500;
const TRANSITION_MS = 900;
const ENTRANCE_MS = 1200;
/** Floating artwork cards on the CRT — denser pack from last 3 days. */
const MAX_CARDS = 8;

type BroadcastHeroProps = {
  slides: HeroSlide[];
  latestHref: string | null;
};

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function BroadcastHero({
  slides,
  latestHref,
}: BroadcastHeroProps) {
  const hasSlides = slides.length > 0;
  const [active, setActive] = useState(0);
  const [phase, setPhase] = useState<"boot" | "live" | "static">(
    hasSlides ? "boot" : "static",
  );
  const [reduced, setReduced] = useState(false);
  const [visible, setVisible] = useState(true);
  const timerRef = useRef<number | null>(null);
  const preloaded = useRef<Set<string>>(new Set());

  const preload = useCallback((url: string | undefined) => {
    if (!url || typeof window === "undefined") return;
    if (preloaded.current.has(url)) return;
    preloaded.current.add(url);
    const img = new window.Image();
    img.decoding = "async";
    img.src = url;
  }, []);

  useEffect(() => {
    const reducedMotion = prefersReducedMotion();
    setReduced(reducedMotion);
    if (reducedMotion || !hasSlides) {
      setPhase("static");
      if (hasSlides) preload(slides[0]?.url);
      return;
    }

    preload(slides[0]?.url);
    if (slides[1]) preload(slides[1].url);

    const boot = window.setTimeout(() => {
      setPhase("live");
    }, ENTRANCE_MS);

    return () => window.clearTimeout(boot);
  }, [hasSlides, preload, slides]);

  useEffect(() => {
    const onVisibility = () => {
      setVisible(document.visibilityState !== "hidden");
    };
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (phase !== "live" || reduced || !hasSlides || slides.length < 2) return;
    if (!visible) {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      return;
    }

    const advance = () => {
      const next = (active + 1) % slides.length;
      preload(slides[(next + 1) % slides.length]?.url);
      setActive(next);
    };

    timerRef.current = window.setTimeout(advance, HOLD_MS);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [active, hasSlides, phase, preload, reduced, slides, visible]);

  // Cap cards to unique slides so the same frame isn't duplicated on-screen.
  const cardCount = Math.min(MAX_CARDS, slides.length);

  return (
    <section
      className={[
        "broadcast-hero",
        "is-solo",
        phase === "boot" ? "is-booting" : "",
        phase === "live" ? "is-live" : "",
        phase === "static" ? "is-static" : "",
        reduced ? "is-reduced" : "",
        hasSlides ? "has-signal" : "no-signal",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label="Connor broadcast"
      style={{ "--bh-transition-ms": `${TRANSITION_MS}ms` } as CSSProperties}
    >
      <div className="broadcast-studio" aria-hidden>
        <div className="broadcast-screen">
          <div className="broadcast-screen-face">
            <div className="broadcast-phosphor" />
            <div className="broadcast-media">
              {hasSlides ? (
                <div className="broadcast-gallery">
                  {Array.from({ length: cardCount }, (_, slot) => {
                    const index = (active + slot) % slides.length;
                    const slide = slides[index];
                    if (!slide) return null;
                    const isActive = slot === 0;
                    return (
                      <figure
                        key={`${slot}-${slide.url}`}
                        data-slot={slot}
                        className={[
                          "broadcast-card",
                          isActive ? "is-active" : "is-satellite",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={slide.url}
                          alt=""
                          className="broadcast-card-img"
                          decoding="async"
                          fetchPriority={isActive ? "high" : "low"}
                          draggable={false}
                        />
                        <figcaption className="broadcast-card-ref">
                          REF.{padRank(slide.signalIndex)}
                        </figcaption>
                      </figure>
                    );
                  })}
                </div>
              ) : (
                <div className="broadcast-fallback" />
              )}
            </div>
            <div className="broadcast-led" />
            <div className="broadcast-scanlines" />
            <div className="broadcast-snow" />
            <div className="broadcast-grain" />
            <div className="broadcast-bloom" />
            <div className="broadcast-vignette" />
            <div className="broadcast-boot-snow" />
            <div className="broadcast-boot-scan" />
          </div>
        </div>
      </div>

      <div className="broadcast-brand">
        <div className="broadcast-brand-mask">
          <h1 className="type-hero broadcast-title broadcast-brand-rise delay-title">
            Connor
          </h1>
          <LiveBeijingDate className="broadcast-date broadcast-brand-rise delay-sub" />
          <p className="broadcast-schedule broadcast-brand-rise delay-sub">
            北京时间每日 12:00 更新当日前沿 AI 日报
          </p>
          <div className="broadcast-cta broadcast-brand-rise delay-cta">
            {latestHref ? (
              <Link
                href={latestHref}
                className="apple-button broadcast-cta-primary"
                scroll={latestHref.startsWith("#") ? false : undefined}
                onClick={
                  latestHref.startsWith("#")
                    ? (event) => {
                        event.preventDefault();
                        pageTurnToReport({ hash: latestHref });
                      }
                    : undefined
                }
              >
                阅读最新日报
              </Link>
            ) : null}
            <Link
              href="/archive"
              className="apple-button broadcast-cta-secondary"
            >
              浏览过去日报
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
