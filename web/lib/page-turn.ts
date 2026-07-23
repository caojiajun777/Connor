/** Homepage hero ↔ report page-turn (CTA / 首页 only — never hijacks wheel). */

import { smoothScrollTo } from "@/lib/smooth-scroll";

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

let busy = false;
let layerEl: HTMLDivElement | null = null;
let timers: number[] = [];

function clearTimers(): void {
  for (const id of timers) window.clearTimeout(id);
  timers = [];
}

function ensureLayer(): HTMLDivElement {
  if (layerEl && layerEl.isConnected) return layerEl;
  const el = document.createElement("div");
  el.className = "home-page-turn-layer";
  el.setAttribute("aria-hidden", "true");
  el.innerHTML = `
    <div class="home-page-turn-shade"></div>
    <div class="home-page-turn-sheet">
      <div class="home-page-turn-sheet-face"></div>
      <div class="home-page-turn-sheet-edge"></div>
    </div>
  `;
  document.body.appendChild(el);
  layerEl = el;
  return el;
}

function clearLayer(): void {
  layerEl?.remove();
  layerEl = null;
}

export function isPageTurning(): boolean {
  return busy;
}

type PageTurnOptions = {
  hash?: string;
  durationMs?: number;
};

function finishTurn(cleanup: () => void, duration: number): void {
  timers.push(
    window.setTimeout(() => {
      cleanup();
      clearLayer();
      busy = false;
    }, duration + 40),
  );
}

/**
 * Flip from CRT hero into today's report (button only).
 */
export function pageTurnToReport(options?: PageTurnOptions): void {
  if (typeof window === "undefined") return;
  const target = document.getElementById("latest-report");
  if (!target) return;

  if (prefersReducedMotion()) {
    smoothScrollTo(target, {
      hash: options?.hash ?? "#latest-report",
      duration: 700,
    });
    return;
  }

  if (busy) return;
  busy = true;
  clearTimers();

  const root = document.documentElement;
  const duration = options?.durationMs ?? 860;
  const layer = ensureLayer();
  root.classList.add("home-page-turning", "home-page-turning--to-report");
  layer.classList.add("is-active", "is-to-report");

  timers.push(
    window.setTimeout(() => {
      const y = Math.round(
        target.getBoundingClientRect().top + window.scrollY,
      );
      window.scrollTo(0, Math.max(0, y));
    }, Math.round(duration * 0.4)),
  );

  finishTurn(() => {
    const y = Math.round(
      target.getBoundingClientRect().top + window.scrollY,
    );
    window.scrollTo(0, Math.max(0, y));
    if (options?.hash) history.replaceState(null, "", options.hash);
    root.classList.remove("home-page-turning", "home-page-turning--to-report");
    root.classList.add("home-report-active");
    layer.classList.remove("is-active", "is-to-report");
  }, duration);
}

/**
 * Flip back up to the hero (首页 / Connor).
 */
export function pageTurnToHome(options?: PageTurnOptions): void {
  if (typeof window === "undefined") return;
  const target = document.getElementById("home");
  if (!target) return;

  if (prefersReducedMotion()) {
    smoothScrollTo(target, { hash: options?.hash ?? "#home", duration: 700 });
    return;
  }

  if (busy) return;
  busy = true;
  clearTimers();

  const root = document.documentElement;
  const duration = options?.durationMs ?? 820;
  const layer = ensureLayer();
  root.classList.add("home-page-turning", "home-page-turning--to-home");
  layer.classList.add("is-active", "is-to-home");

  timers.push(
    window.setTimeout(() => {
      window.scrollTo(0, 0);
    }, Math.round(duration * 0.34)),
  );

  finishTurn(() => {
    window.scrollTo(0, 0);
    if (options?.hash) history.replaceState(null, "", options.hash);
    root.classList.remove(
      "home-page-turning",
      "home-page-turning--to-home",
      "home-report-active",
    );
    layer.classList.remove("is-active", "is-to-home");
  }, duration);
}
