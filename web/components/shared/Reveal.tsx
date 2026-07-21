"use client";

import {
  useEffect,
  useRef,
  type CSSProperties,
  type ElementType,
  type HTMLAttributes,
  type ReactNode,
} from "react";

type RevealProps = {
  children: ReactNode;
  className?: string;
  as?: ElementType;
  delayMs?: number;
  once?: boolean;
  /** Softer travel — preferred for long reading surfaces. */
  soft?: boolean;
} & Omit<HTMLAttributes<HTMLElement>, "className" | "children" | "style">;

function isNearViewport(node: HTMLElement): boolean {
  const rect = node.getBoundingClientRect();
  const vh = window.innerHeight || 0;
  // Reveal early so above-the-fold content never sits invisible.
  return rect.top < vh * 0.92 && rect.bottom > -40;
}

export function Reveal({
  children,
  className = "",
  as: Tag = "div",
  delayMs = 0,
  once = true,
  soft = false,
  ...rest
}: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.classList.add("is-visible");
      return;
    }

    if (isNearViewport(node)) {
      // Keep delay for stagger, but ensure we become visible without scroll.
      node.classList.add("is-visible");
      if (once) return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          node.classList.add("is-visible");
          if (once) observer.disconnect();
        } else if (!once) {
          node.classList.remove("is-visible");
        }
      },
      { threshold: 0.08, rootMargin: "48px 0px -6% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [once]);

  const style = {
    "--reveal-delay": `${delayMs}ms`,
  } as CSSProperties;

  return (
    <Tag
      ref={ref}
      className={[soft ? "reveal reveal-soft" : "reveal", className]
        .filter(Boolean)
        .join(" ")}
      style={style}
      {...rest}
    >
      {children}
    </Tag>
  );
}
