import type { ReactNode } from "react";

type SignalMarkerProps = {
  className?: string;
  children?: ReactNode;
  /** When true, only render the status dot. */
  dotOnly?: boolean;
};

/** Connor signal language: blue status dot + optional meta row. */
export function SignalMarker({
  className = "",
  children,
  dotOnly = false,
}: SignalMarkerProps) {
  if (dotOnly) {
    return (
      <span
        className={["signal-dot", className].filter(Boolean).join(" ")}
        aria-hidden
      />
    );
  }

  return (
    <div
      className={["signal-marker", className].filter(Boolean).join(" ")}
    >
      <span className="signal-dot" aria-hidden />
      {children ? <div className="signal-marker-body">{children}</div> : null}
    </div>
  );
}
