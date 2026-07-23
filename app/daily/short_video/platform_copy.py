"""Deterministic multi-platform captions for manual upload (P2)."""

from __future__ import annotations

from pathlib import Path

from app.daily.short_video.schemas import VideoPlan


def _story_lines(plan: VideoPlan, *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for idx, story in enumerate(plan.stories[:limit], start=1):
        mark = "①②③④⑤⑥⑦⑧⑨⑩"[idx - 1] if idx <= 10 else f"{idx}."
        lines.append(f"{mark} {story.title}")
    return lines


def build_douyin_copy(plan: VideoPlan) -> str:
    lines = [
        f"每日 AI 速报｜{plan.report_date}",
        plan.hook,
        "",
        *_story_lines(plan),
        "",
        "完整日报与原始信源：aiconnor.cn",
        "",
        "#AI速报 #人工智能 #科技新闻 #Connor",
    ]
    return "\n".join(lines) + "\n"


def build_xiaohongshu_copy(plan: VideoPlan) -> str:
    lines = [
        f"今日 AI 速报（{plan.report_date}）",
        "",
        plan.hook,
        "",
        "今天这几条值得看：",
        *_story_lines(plan),
        "",
        "为什么看 Connor：按评分筛选 + 原文信源可核对。",
        "完整版 → aiconnor.cn",
        "",
        "#AI #科技资讯 #每日速报 #效率工具",
    ]
    return "\n".join(lines) + "\n"


def build_bilibili_copy(plan: VideoPlan) -> str:
    lead = plan.stories[0].title if plan.stories else plan.hook
    lines = [
        f"【每日 AI 速报】{plan.report_date}｜{lead}",
        "",
        "简介：",
        plan.hook,
        "",
        "时间轴大意：",
        "0:00 钩子",
        "片头后进入头条与速报条目",
        "",
        *_story_lines(plan),
        "",
        "完整日报：https://aiconnor.cn",
        "声明：内容来自公开信源整理，未证实信息会标注。",
    ]
    return "\n".join(lines) + "\n"


def write_platform_copy(plan: VideoPlan, day_dir: Path) -> dict[str, Path]:
    day_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "douyin.txt": build_douyin_copy(plan),
        "xiaohongshu.txt": build_xiaohongshu_copy(plan),
        "bilibili.txt": build_bilibili_copy(plan),
    }
    out: dict[str, Path] = {}
    for name, text in mapping.items():
        path = day_dir / name
        path.write_text(text, encoding="utf-8")
        out[name] = path
    return out
