import { HomeJumpButton } from "@/components/shared/HomeJumpButton";
import { SiteFooter } from "@/components/shared/SiteFooter";
import { SiteNav } from "@/components/shared/SiteNav";

interface SiteShellProps {
  children: React.ReactNode;
  showFooter?: boolean;
  /** Homepage CRT continuum — cobalt phosphor, dark archive. */
  tone?: "default" | "crt";
}

export function SiteShell({
  children,
  showFooter = true,
  tone = "default",
}: SiteShellProps) {
  const isCrt = tone === "crt";

  return (
    <div
      className={[
        "relative flex min-h-screen flex-col",
        isCrt ? "home-crt" : "bg-background text-text-primary",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <header className="site-header">
        <SiteNav />
      </header>
      <main className="flex-1">{children}</main>
      <HomeJumpButton />
      {showFooter ? <SiteFooter tone={tone} /> : null}
    </div>
  );
}
