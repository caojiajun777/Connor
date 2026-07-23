"""Speech shaping for mixed Chinese / English news TTS.

Keep original English brand spellings. Only reshape text so Neural Chinese
voices pause and pronounce technical terms more cleanly:

- space English islands away from CJK
- split glued product+version forms (Qwen3.8 → Qwen 3.8)
- letter-space short acronyms (API → A P I)
- soft-break known compound brands (DeepMind → Deep Mind)
- localize parameter-size suffixes (2B → 二十亿) — numbers, not brand translation
"""

from __future__ import annotations

import re

_DIGIT_MAP = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}


def _speak_int(n: int) -> str:
    if n < 0 or n > 9999:
        return str(n)
    if n < 10:
        return _DIGIT_MAP[str(n)]
    if n < 20:
        return "十" if n == 10 else "十" + _DIGIT_MAP[str(n % 10)]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _DIGIT_MAP[str(tens)] + "十" + (_DIGIT_MAP[str(ones)] if ones else "")
    if n < 1000:
        hundreds, rem = divmod(n, 100)
        if rem == 0:
            return _DIGIT_MAP[str(hundreds)] + "百"
        if rem < 10:
            return _DIGIT_MAP[str(hundreds)] + "百零" + _DIGIT_MAP[str(rem)]
        return _DIGIT_MAP[str(hundreds)] + "百" + _speak_int(rem)
    thousands, rem = divmod(n, 1000)
    if rem == 0:
        return _DIGIT_MAP[str(thousands)] + "千"
    if rem < 100:
        return _DIGIT_MAP[str(thousands)] + "千零" + _speak_int(rem)
    return _DIGIT_MAP[str(thousands)] + "千" + _speak_int(rem)


def _speak_decimal(whole: str, frac: str | None = None) -> str:
    spoken = _speak_int(int(whole))
    if frac:
        spoken += "点" + "".join(_DIGIT_MAP.get(ch, ch) for ch in frac)
    return spoken


# Keep English spelling; only insert readability breaks.
_COMPOUND_BRANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Flash[\s-]*Lite", re.I), "Flash Lite"),
    (re.compile(r"Flash[\s-]*Cyber", re.I), "Flash Cyber"),
    (re.compile(r"Hugging\s*Face", re.I), "Hugging Face"),
    (re.compile(r"OpenRouter", re.I), "Open Router"),
    (re.compile(r"OpenAI", re.I), "Open AI"),
    (re.compile(r"DeepMind", re.I), "Deep Mind"),
    (re.compile(r"DeepSeek[\s-]*V\.?\s*3", re.I), "Deep Seek V 3"),
    (re.compile(r"DeepSeek", re.I), "Deep Seek"),
    (re.compile(r"CodeMender", re.I), "Code Mender"),
    (re.compile(r"ChatGPT", re.I), "Chat GPT"),
    (re.compile(r"Blackwell\s*Ultra", re.I), "Blackwell Ultra"),
    (re.compile(r"Nemotron\s*3\s*Ultra", re.I), "Nemotron 3 Ultra"),
    (re.compile(r"Cosmos\s*3\s*Edge", re.I), "Cosmos 3 Edge"),
    (re.compile(r"Laguna\s*S\s*2\.1", re.I), "Laguna S 2.1"),
    (re.compile(r"Jetson\s*Thor", re.I), "Jetson Thor"),
    (re.compile(r"Xiaomi[\s_-]*Robotics[\s_-]*1", re.I), "Xiaomi Robotics 1"),
    (re.compile(r"\bvLLM\s*Omni\b", re.I), "V L L M Omni"),
    (re.compile(r"\bvLLM\b", re.I), "V L L M"),
]

# Short Latin acronyms that Chinese voices often slur — spell letter by letter.
_ACRONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z])API(?![A-Za-z])", re.I), "A P I"),
    (re.compile(r"(?<![A-Za-z])GPU(?![A-Za-z])", re.I), "G P U"),
    (re.compile(r"(?<![A-Za-z])TTS(?![A-Za-z])", re.I), "T T S"),
    (re.compile(r"(?<![A-Za-z])MoE(?![A-Za-z])", re.I), "M O E"),
    (re.compile(r"(?<![A-Za-z])IMO(?![A-Za-z])", re.I), "I M O"),
    (re.compile(r"(?<![A-Za-z])NLP(?![A-Za-z])", re.I), "N L P"),
    (re.compile(r"(?<![A-Za-z])LLM(?![A-Za-z])", re.I), "L L M"),
    # AI速报 / 物理AI — \b fails next to CJK.
    (re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])", re.I), "A I"),
]

_SIZE_RE = re.compile(
    r"(?<![\d.])(\d{1,3})(?:\.(\d{1,3}))?\s*([BbTt])(?![A-Za-z])"
)
_LETTER_DIGIT_RE = re.compile(r"([A-Za-z])(\d)")
_DIGIT_LETTER_RE = re.compile(r"(\d)([A-Za-z])")
_CJK_LATIN_RE = re.compile(r"([\u4e00-\u9fff])([A-Za-z])")
_LATIN_CJK_RE = re.compile(r"([A-Za-z])([\u4e00-\u9fff])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _size_to_speech(match: re.Match[str]) -> str:
    """Read 2B / 2.4T as Chinese quantities (not brand names)."""
    whole, frac, unit = match.group(1), match.group(2), match.group(3).upper()
    spoken = _speak_decimal(whole, frac)
    if unit == "B":
        return spoken + "亿"
    return spoken + "万亿"


def rewrite_for_speech(text: str) -> str:
    """Shape mixed CN/EN copy for clearer TTS — keep English brands intact."""
    out = (text or "").strip()
    if not out:
        return out

    for pattern, repl in _COMPOUND_BRANDS:
        out = pattern.sub(repl, out)
    for pattern, repl in _ACRONYMS:
        out = pattern.sub(repl, out)

    # Qwen3.8 / GPT5 → Qwen 3.8 / GPT 5
    out = _LETTER_DIGIT_RE.sub(r"\1 \2", out)
    out = _DIGIT_LETTER_RE.sub(r"\1 \2", out)

    # Parameter sizes before generic cleanup.
    out = _SIZE_RE.sub(_size_to_speech, out)

    # Isolate Latin tokens from Chinese so the voice can switch cleanly.
    out = _CJK_LATIN_RE.sub(r"\1 \2", out)
    out = _LATIN_CJK_RE.sub(r"\1 \2", out)

    out = _MULTI_SPACE_RE.sub(" ", out)
    out = re.sub(r"\s+([，。！？、；,:])", r"\1", out)
    return out.strip()
