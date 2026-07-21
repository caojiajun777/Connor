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

/**
 * Smoothly scroll an element into view.
 * Temporarily disables homepage snap so the ease isn't yanked mid-flight.
 */
export function smoothScrollTo(
  target: HTMLElement,
  options?: { duration?: number; hash?: string },
): void {
  if (typeof window === "undefined") return;

  if (prefersReducedMotion()) {
    target.scrollIntoView({ behavior: "auto", block: "start" });
    if (options?.hash) history.replaceState(null, "", options.hash);
    return;
  }

  const duration = options?.duration ?? 1100;
  const root = document.documentElement;
  const startY = window.scrollY;
  const endY = Math.round(
    target.getBoundingClientRect().top + window.scrollY,
  );
  const distance = endY - startY;

  if (Math.abs(distance) < 2) {
    if (options?.hash) history.replaceState(null, "", options.hash);
    return;
  }

  if (activeFrame) cancelAnimationFrame(activeFrame);
  root.classList.add("home-snap-locking");

  const t0 = performance.now();

  const step = (now: number) => {
    const t = Math.min(1, (now - t0) / duration);
    const y = startY + distance * easeOutQuint(t);
    window.scrollTo(0, y);

    if (t < 1) {
      activeFrame = requestAnimationFrame(step);
      return;
    }

    activeFrame = 0;
    window.scrollTo(0, endY);
    if (options?.hash) history.replaceState(null, "", options.hash);
    // Re-enable snap after the paint settles.
    requestAnimationFrame(() => {
      root.classList.remove("home-snap-locking");
    });
  };

  activeFrame = requestAnimationFrame(step);
}
