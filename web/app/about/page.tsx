import type { Metadata } from "next";
import Link from "next/link";

import { Reveal } from "@/components/shared/Reveal";
import { SignalMarker } from "@/components/shared/SignalMarker";
import { SignalMeta } from "@/components/shared/SignalMeta";
import { SiteShell } from "@/components/shared/SiteShell";
import { padRank } from "@/lib/format";

export const metadata: Metadata = {
  title: "About",
  description:
    "Connor — created by Jiajun. Automated agent pipeline for frontier AI briefings.",
};

const pipeline = [
  {
    label: "COLLECT",
    title: "采集",
    body: "从精选信源持续抓取公开动态，保留原文、时间与出处。",
  },
  {
    label: "EVALUATE",
    title: "评测",
    body: "Agent 对信号做筛选与排序，压掉噪声，留下真正值得阅读的前沿信息。",
  },
  {
    label: "WRITE",
    title: "写作",
    body: "自动打包事件、撰写导语与正文，生成可公开阅读的每日简报。",
  },
];

export default function AboutPage() {
  return (
    <SiteShell tone="crt">
      <section
        className="home-archive reading-shell scroll-mt-16 pt-28 pb-16 sm:pt-32 sm:pb-20"
        aria-label="About Connor"
      >
        <Reveal soft className="max-w-[720px]">
          <SignalMarker className="mb-4">
            <SignalMeta as="span">About</SignalMeta>
          </SignalMarker>
          <h1 className="type-headline text-[40px] leading-[1.05] tracking-[-0.04em] sm:text-[52px]">
            Connor
          </h1>
          <p className="type-lead mt-5 max-w-[36rem] text-[18px] text-[var(--text-secondary)] sm:text-[20px]">
            提供前沿的 AI 资讯。
            <br />
            用全自动 Agent 链路完成收集、评测与写作。
          </p>
          <p className="mt-6 type-body text-[15px] text-[var(--text-tertiary)] sm:text-[16px]">
            Created by{" "}
            <span className="font-semibold text-[var(--crt-phosphor,#9ecfff)]">
              Jiajun
            </span>
          </p>
        </Reveal>

        <Reveal soft delayMs={80} className="mt-16 max-w-[720px] sm:mt-20">
          <SignalMarker className="mb-6">
            <SignalMeta as="span">Pipeline</SignalMeta>
          </SignalMarker>
          <p className="type-body mb-8 max-w-[34rem] text-[16px] text-[var(--text-secondary)] sm:text-[17px]">
            Connor
            不是人工刷信息流的编辑台，而是一条可重复运行的自动链路：每天把公开世界里的 AI
            前沿信号，收敛成一份可读的日报。
          </p>

          <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
            {pipeline.map((step, index) => (
              <article
                key={step.label}
                className="grid gap-3 py-8 sm:grid-cols-[5rem_1fr] sm:gap-10 sm:py-9"
              >
                <SignalMeta
                  as="p"
                  className="type-signal-accent pt-1 text-[12px] tracking-[0.16em]"
                >
                  {padRank(index + 1)}
                </SignalMeta>
                <div>
                  <p className="type-signal mb-2 text-[11px] tracking-[0.18em] text-[var(--crt-phosphor,#9ecfff)]">
                    {step.label}
                  </p>
                  <h2 className="type-headline text-[22px] sm:text-[26px]">
                    {step.title}
                  </h2>
                  <p className="type-body mt-2 text-[15px] text-[var(--text-secondary)] sm:text-[16px]">
                    {step.body}
                  </p>
                </div>
              </article>
            ))}
          </div>
        </Reveal>

        <Reveal soft delayMs={140} className="mt-14 max-w-[720px] sm:mt-16">
          <p className="type-lead-italic max-w-[32rem] text-[17px] text-[var(--text-secondary)] sm:text-[18px]">
            冷静阅读，清晰出处——把注意力留给真正向前的那几条信号。
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
            <Link href="/archive" className="apple-button">
              浏览过去日报
            </Link>
            <Link
              href="/"
              className="apple-link text-[15px] text-[var(--text-secondary)]"
            >
              回到首页
            </Link>
          </div>
        </Reveal>
      </section>
    </SiteShell>
  );
}
