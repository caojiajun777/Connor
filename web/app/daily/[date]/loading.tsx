import { SiteShell } from "@/components/shared/SiteShell";

export default function DailyLoading() {
  return (
    <SiteShell>
      <div className="reading-shell animate-pulse py-14">
        <div className="mx-auto h-3 w-32 rounded bg-surface-secondary" />
        <div className="mx-auto mt-4 h-10 w-3/4 max-w-xl rounded bg-surface-secondary" />
        <div className="mx-auto mt-4 h-20 w-full max-w-2xl rounded bg-surface-secondary" />
        <div className="mx-auto mt-10 max-w-[720px] space-y-5">
          <div className="h-40 rounded-medium bg-surface-secondary" />
          <div className="h-40 rounded-medium bg-surface-secondary" />
        </div>
      </div>
    </SiteShell>
  );
}
