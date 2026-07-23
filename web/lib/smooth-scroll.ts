/** Eased viewport scroll — silkier than native `behavior: "smooth"`. */

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** easeOutQuint — long glide, soft landing */
function easeOutQuint(t: number): number {
  return 1 - Math.pow(1 - t, 5);
}

let activeFrame = 0;
let settleTimers: number[] = [];
let settleObserver: ResizeObserver | null = null;

function clearSettleWatch(): void {
  for (const id of settleTimers) window.clearTimeout(id);
  settleTimers = [];
  if (settleObserver) {
    settleObserver.disconnect();
    settleObserver = null;
  }
}

/** Fixed header clearance for in-report anchors (TOC → digest). */
export function headerScrollOffset(): number {
  const nav = document.querySelector(".site-nav");
  const h = nav?.getBoundingClientRect().height ?? 0;
  return Math.round(h + 20);
}

function targetScrollY(target: HTMLElement, offset: number): number {
  return Math.max(
    0,
    Math.round(target.getBoundingClientRect().top + window.scrollY - offset),
  );
}

/**
 * After the first jump, images/fonts above the target often expand and
 * leave the headline under the fold — re-align while layout settles.
 */
function watchAnchorSettle(target: HTMLElement, offset: number): void {
  clearSettleWatch();

  const correct = () => {
    if (!target.isConnected) return;
    const y = targetScrollY(target, offset);
    if (Math.abs(window.scrollY - y) > 3) {
      window.scrollTo(0, y);
    }
  };

  requestAnimationFrame(() => {
    requestAnimationFrame(correct);
  });

  settleTimers.push(window.setTimeout(correct, 120));
  settleTimers.push(window.setTimeout(correct, 360));
  settleTimers.push(window.setTimeout(correct, 800));

  const root =
    document.querySelector(".report-reading") ||
    document.querySelector(".report-page-shell") ||
    document.body;

  if (typeof ResizeObserver !== "undefined" && root) {
    settleObserver = new ResizeObserver(() => correct());
    settleObserver.observe(root);
    settleTimers.push(
      window.setTimeout(() => {
        settleObserver?.disconnect();
        settleObserver = null;
      }, 1600),
    );
  }
}

export type SmoothScrollOptions = {
  duration?: number;
  hash?: string;
  /** Extra top inset in px, or `"header"` for fixed nav clearance. */
  offset?: number | "header";
  /** Re-measure after late layout (images). Default true when offset is header. */
  settle?: boolean;
};

/**
 * Smoothly scroll an element into view (CTA / nav / TOC).
 * Wheel scrolling stays native via `scroll-behavior: auto`.
 */
export function smoothScrollTo(
  target: HTMLElement,
  options?: SmoothScrollOptions,
): void {
  if (typeof window === "undefined") return;

  const offset =
    options?.offset === "header"
      ? headerScrollOffset()
      : typeof options?.offset === "number"
        ? options.offset
        : 0;
  const shouldSettle =
    options?.settle ?? options?.offset === "header";

  const endY = targetScrollY(target, offset);

  if (prefersReducedMotion()) {
    window.scrollTo(0, endY);
    if (options?.hash) history.replaceState(null, "", options.hash);
    if (shouldSettle) watchAnchorSettle(target, offset);
    return;
  }

  const duration = options?.duration ?? 900;
  const startY = window.scrollY;
  const distance = endY - startY;

  if (Math.abs(distance) < 2) {
    if (options?.hash) history.replaceState(null, "", options.hash);
    if (shouldSettle) watchAnchorSettle(target, offset);
    return;
  }

  if (activeFrame) cancelAnimationFrame(activeFrame);
  clearSettleWatch();

  const t0 = performance.now();

  const step = (now: number) => {
    const t = Math.min(1, (now - t0) / duration);
    window.scrollTo(0, startY + distance * easeOutQuint(t));

    if (t < 1) {
      activeFrame = requestAnimationFrame(step);
      return;
    }

    activeFrame = 0;
    // Recompute end — media above may have grown mid-flight.
    const settledY = targetScrollY(target, offset);
    window.scrollTo(0, settledY);
    if (options?.hash) history.replaceState(null, "", options.hash);
    if (shouldSettle) watchAnchorSettle(target, offset);
  };

  activeFrame = requestAnimationFrame(step);
}
