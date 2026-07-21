import type { HTMLAttributes, ReactNode } from "react";

type SignalMetaProps = {
  children: ReactNode;
  className?: string;
  as?: "p" | "span" | "div";
} & Omit<HTMLAttributes<HTMLElement>, "className" | "children">;

/** Uppercase mono micro-label for dates, ranks, source counts. */
export function SignalMeta({
  children,
  className = "",
  as: Tag = "p",
  ...rest
}: SignalMetaProps) {
  return (
    <Tag
      className={["type-signal", className].filter(Boolean).join(" ")}
      {...rest}
    >
      {children}
    </Tag>
  );
}
