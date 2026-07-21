import Link from "next/link";

interface HomeLoadNoticeProps {
  variant: "error" | "empty";
}

/** Soft failure / empty state under the CRT hero when today's report is missing. */
export function HomeLoadNotice({ variant }: HomeLoadNoticeProps) {
  const title =
    variant === "error" ? "今日日报暂时无法加载" : "今日日报尚未发布";
  const body =
    variant === "error"
      ? "服务稍候再试，或先浏览往期日报。"
      : "新的一天还在路上。你可以先看往期归档。";

  return (
    <section
      className="home-panel--report flex min-h-[40svh] items-center justify-center px-6 py-16"
      aria-label="Report status"
    >
      <div className="report-surface max-w-lg px-8 py-12 text-center">
        <p className="type-headline text-[24px] sm:text-[28px]">{title}</p>
        <p className="type-lead mt-3 text-[16px]">{body}</p>
        <div className="mt-8">
          <Link href="/archive" className="apple-button">
            浏览过去日报
          </Link>
        </div>
      </div>
    </section>
  );
}
