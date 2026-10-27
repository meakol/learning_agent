from __future__ import annotations

import math
import re
from typing import Any
from .prompts import load, load_json
from .text_utils import is_admin_heading, is_admin_text, strip_admin_lines

LEVELS: list[dict[str, Any]] = [
    {"level": 1, "zh": "速览", "en": "Sprint", "desc": "只保留最核心的考点，考前 3 分钟扫一遍。"},
    {"level": 2, "zh": "精简", "en": "Brief", "desc": "每页提炼 1–2 个要点，快速建立框架。"},
    {"level": 3, "zh": "标准", "en": "Standard", "desc": "完整的复习笔记：定义、原理、步骤与来源页码。"},
    {"level": 4, "zh": "详细", "en": "Detailed", "desc": "补充解释、公式条件、易错点与例子。"},
    {"level": 5, "zh": "精讲", "en": "Deep dive", "desc": "深度理解：背景、对比、推导、考法与自测。"},
]

LEVEL_RULES = {int(key): value for key, value in load_json("rules/levels_zh.json").items()}
LEVEL_RULES_EN = {int(key): value for key, value in load_json("rules/levels_en.json").items()}
LANGUAGE_RULES = load_json("rules/language_rules.json")

SYSTEM_PROMPT = load("notes/system_zh.md")

SYSTEM_PROMPT_EN = load("notes/system_en.md")

BILINGUAL_EXAMPLE = load("notes/bilingual_example.md")

ENGLISH_EXAMPLE = load("notes/english_example.md")


def level_info(level: int) -> dict[str, Any]:
    return LEVELS[max(1, min(5, int(level))) - 1]


def build_context(doc: dict[str, Any], max_chars: int) -> tuple[str, bool]:
    slides = doc.get("slides", [])
    total = sum(len(s.get("text", "")) + len(s.get("notes", "")) for s in slides)
    truncated = total > max_chars
    per_slide = max(500, max_chars // max(1, len(slides))) if truncated else 10**9

    chunks: list[str] = []
    for slide in slides:
        text = strip_admin_lines((slide.get("text") or "").strip())
        notes = strip_admin_lines((slide.get("notes") or "").strip())
        if not text and not notes:
            continue
        body = text
        if notes:
            body += f"\n[讲者备注] {notes}"
        if len(body) > per_slide:
            body = body[:per_slide].rstrip() + " …"
        visual_hint = ""
        visuals = [
            visual
            for visual in (slide.get("visuals") or [])
            if float(visual.get("confidence") or 0) >= 0.55
        ]
        if visuals:
            kinds = {visual.get("kind") for visual in visuals}
            labels = []
            if kinds & {"image", "diagram"}:
                labels.append("图示")
            if "table" in kinds:
                labels.append("表格")
            visual_hint = " | 可截取：" + "、".join(labels or ["图示"])
        chunks.append(
            f"<<< 第 {slide['index']} 页 | {slide.get('title') or '未命名'}{visual_hint} >>>\n{body}"
        )
    return "\n\n".join(chunks), truncated


def build_chunk_messages(
    doc: dict[str, Any],
    slides: list[dict[str, Any]],
    language: str,
    level: int,
    focus: str = "",
) -> list[dict[str, str]]:
    """Build messages for one pipeline chunk while preserving note rules."""
    chunk_doc = dict(doc)
    chunk_doc["page_count"] = len(slides)
    chunk_doc["slides"] = slides
    messages, _ = build_messages(chunk_doc, language, level, 10**9, focus)
    return messages


def build_messages(
    doc: dict[str, Any],
    language: str,
    level: int,
    max_chars: int,
    focus: str = "",
) -> tuple[list[dict[str, str]], bool]:
    context, truncated = build_context(doc, max_chars)
    language = language if language in LANGUAGE_RULES else "zh"
    info = level_info(level)
    rules = LEVEL_RULES_EN[info["level"]] if language == "en" else LEVEL_RULES[info["level"]]
    system_prompt = SYSTEM_PROMPT_EN if language == "en" else SYSTEM_PROMPT

    user_parts = [
        f"【课件信息】文件名：{doc.get('filename', '课件')}；共 {doc.get('page_count', 0)} 页。",
        f"【输出语言】{LANGUAGE_RULES[language]}",
        f"【笔记详细程度】第 {info['level']} 级 / 5（{info['zh']}）—— {rules}",
        "【格式示例】（仅示范结构，不要照抄内容）",
        "## 1. 小节标题 [p.1-2]\n- [核心] 改写后的知识点… [p.1]\n- [重点] 易错点或条件… [p.2]",
    ]
    if language == "bilingual":
        user_parts += ["【双语格式示例】", BILINGUAL_EXAMPLE]
    elif language == "en":
        user_parts += ["【English style example】", ENGLISH_EXAMPLE]
        user_parts.append(
            "【ENGLISH OUTPUT CHECK】Use note fragments, not prose. Each bullet <=18 words; "
            "each paragraph <=2 sentences. If a group has 3+ parallel points, you MUST use "
            "a :::branches block. Do not output one long paragraph per slide."
        )
    if focus.strip():
        user_parts.append(f"【学习者补充要求】{focus.strip()[:500]}")
    user_parts += [
        "【课件内容开始】",
        context,
        "【课件内容结束】",
        "【输出前自检】是否把长句改写成了短条目？是否避免连续照抄？并列要点是否使用平行结构或 branches？结构组件是否过多？段落之间是否留白？",
        "现在直接输出 Markdown 笔记正文。",
    ]
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ], truncated


# --------------------------------------------------------------------------- #
# Local fallback: extractive notes (no LLM required)
# --------------------------------------------------------------------------- #
CUE_WORDS = (
    "定义", "概念", "原理", "公式", "定理", "定律", "性质", "特征", "特点",
    "分类", "步骤", "方法", "流程", "条件", "区别", "对比", "优势", "缺点",
    "局限", "重要", "关键", "考点", "注意", "必须", "核心", "本质", "结论",
    "目标", "损失", "优化", "计算", "推导", "definition", "theorem", "formula",
    "important", "key", "must", "note", "difference", "advantage", "limitation",
    "step", "process", "because",
)
SKIP_TITLES = {
    "目录", "目录 contents", "agenda", "contents", "谢谢", "谢谢观看",
    "thank you", "thanks", "q&a", "questions",
}
PARALLEL_CUES = (
    "、", "/", "分类", "组成", "要素", "步骤", "流程", "对比", "区别",
    "特点", "优势", "缺点", "方法", "结构", "路线", "类型", "层级",
    "comparison", "types", "components", "steps", "process", "advantages",
    "disadvantages", "methods", "structure", "classification", " vs ",
)
STOP_CHARS = set("的了和与及或是为在有对从把被这那么就都而及其之一个中上下使用进行可以以及通过我们你他她它")


def _split_sentences(text: str) -> list[str]:
    chunks: list[str] = []
    for line in text.splitlines():
        line = line.strip(" \t•·-–—*")
        if not line:
            continue
        pieces = re.split(r"(?<=[。！？；!?;])\s*|(?<=\.)\s+", line)
        for piece in pieces:
            piece = piece.strip()
            if piece:
                chunks.append(piece)
    return chunks


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？；：、,.!?;:'\"“”‘’()（）\[\]【】]", "", text).lower()


def _score_sentence(sentence: str, title: str, position: int) -> float:
    lower = sentence.lower()
    score = 1.0
    score += sum(2.2 for cue in CUE_WORDS if cue in lower or cue in sentence)
    if re.search(r"\d", sentence):
        score += 1.0
    if re.search(r"[=＝≈≤≥→]|sqrt|softmax|∑|\(|\)", lower):
        score += 0.8
    if 20 <= len(sentence) <= 80:
        score += 0.8
    elif len(sentence) < 10:
        score -= 1.2
    title_chars = {c for c in title if "\u4e00" <= c <= "\u9fff" and c not in STOP_CHARS}
    if title_chars:
        overlap = len(title_chars & set(sentence)) / len(title_chars)
        score += overlap * 2.5
    score += max(0, 0.8 - position * 0.15)
    return score


def _clean_sentence(sentence: str) -> str:
    sentence = re.sub(r"^[①-⑩]\s*", "", sentence.strip())
    sentence = re.sub(r"^\d+[.)、]\s*", "", sentence)
    sentence = re.sub(r"\s{2,}", " ", sentence)
    if len(sentence) > 320:
        sentence = sentence[:318].rstrip() + "…"
    return sentence


def _clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _fragment_sentence(sentence: str, level: int) -> list[str]:
    """Break long extracted sentences into short note-sized fragments."""
    text = re.sub(r"\s+", " ", sentence.strip())
    if not text:
        return []
    latin = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    is_english = latin > cjk * 2
    formulaish = bool(re.search(r"[=＝≈≤≥→]|sqrt|softmax|∑|\^", text))

    if is_english:
        max_words = 18 if level <= 2 else 20 if level == 3 else 24
        words = text.split()
        if len(words) <= max_words:
            return [text]
        if formulaish:
            pieces = re.split(r";\s*", text)
        else:
            pieces = re.split(r";\s*|:\s+|,\s+", text)
        refined: list[str] = []
        connector = (
            r"\s+(?=(?:and|but|because|while|whereas|so|if|when|after|before|then)\s+)"
        )
        for piece in pieces:
            piece = piece.strip(" ,;:")
            if not piece:
                continue
            if len(piece.split()) > max_words:
                refined.extend(
                    part.strip(" ,;:")
                    for part in re.split(connector, piece, flags=re.IGNORECASE)
                    if part.strip(" ,;:")
                )
            else:
                refined.append(piece)
        chunks: list[list[str]] = []
        current: list[str] = []
        for piece in refined:
            piece_words = piece.split()
            if current and len(current) + len(piece_words) > max_words:
                chunks.append(current)
                current = piece_words
            else:
                current.extend(piece_words)
            if len(current) > max_words:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
        result = []
        for words_chunk in chunks:
            fragment = " ".join(words_chunk)
            fragment = re.sub(r"^(?:and|but|so)\s+", "", fragment, flags=re.IGNORECASE).strip(" ,;:")
            if not fragment:
                continue
            if fragment[0].islower():
                fragment = fragment[0].upper() + fragment[1:]
            if fragment[-1] not in ".!?;:":
                fragment += "."
            result.append(fragment)
        return result or [text]

    max_chars = 42 if level <= 2 else 55 if level == 3 else 70
    if len(text) <= max_chars:
        return [text]
    if formulaish:
        pieces = re.split(r"(?<=[；;])", text)
    else:
        pieces = re.split(r"(?<=[；;])|，", text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        piece = piece.strip(" ，,；;")
        if not piece:
            continue
        if current and len(current) + len(piece) + 1 > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = (current + "，" + piece) if current else piece
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk] or [text]


def _table_block(element: dict[str, Any], title: str) -> str:
    rows = element.get("rows") or []
    if len(rows) < 2:
        return ""
    headers = [_clean_cell(cell).replace("|", "/") for cell in rows[0]]
    if not any(headers):
        return ""
    width = len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in rows[1:]:
        cells = [_clean_cell(cell).replace("|", "/") for cell in row[:width]]
        cells += [""] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
    return ":::table " + (title or "对比表") + "\n" + "\n".join(lines) + "\n:::"


def _is_layout_noise(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    lower = text.lower()
    if re.fullmatch(r"\d+\s*(?:/|of)\s*\d+", lower):
        return True
    if re.fullmatch(r"第?\s*\d+\s*页?", lower):
        return True
    if re.fullmatch(r"(?:p|page)\s*\.?\s*\d+", lower):
        return True
    # Kicker labels and decorative all-caps text from designed slides.
    if len(text) <= 60 and text.upper() == text and re.search(r"[A-Z]", text):
        if not re.search(r"\d", text):
            return True
    if lower.startswith(("agenda", "motivation", "intuition", "takeaways", "comparison")):
        return True
    # Table rows are handled separately with their header context.
    if text.count("|") >= 2:
        return True
    # Bare self-test questions and short section labels are not knowledge points.
    if re.search(r"[？?]\s*$", text) and len(text) < 60:
        return True
    if not re.search(r"[。！？.!?：:=]", text) and len(_normalize(text)) < 12:
        return True
    # Card labels such as "Q · Query" or "Add / Norm" carry no standalone meaning.
    if re.fullmatch(r"[A-Za-z][A-Za-z\s]{0,20}[·•:：/&–—-]\s*[A-Za-z][A-Za-z\s]{0,20}", text):
        return True
    return False


def _deck_noise_lines(slides: list[dict[str, Any]]) -> set[str]:
    from collections import Counter

    counter: Counter[str] = Counter()
    for slide in slides:
        seen: set[str] = set()
        for line in (slide.get("text") or "").splitlines():
            key = _normalize(line)
            if len(key) >= 6 and key not in seen:
                seen.add(key)
                counter[key] += 1
    threshold = max(3, math.ceil(len(slides) * 0.5))
    return {line for line, count in counter.items() if count >= threshold}


def _looks_like_cover(slide: dict[str, Any], line_count: int) -> bool:
    if slide.get("index") != 1:
        return False
    raw = (slide.get("text") or "").lower()
    if line_count > 10:
        return False
    if any(marker in raw for marker in ("lecture", "课件", "课程", "演示", "presentation")):
        return True
    if re.search(r"[。！？.!?]", raw):
        return False
    return not any(cue in raw for cue in CUE_WORDS)


def local_notes(
    doc: dict[str, Any],
    language: str,
    level: int,
    reason: str = "",
) -> str:
    """Extractive fallback used when no LLM API key is configured."""
    level = max(1, min(5, level))
    max_per_slide = {1: 2, 2: 3, 3: 4, 4: 6, 5: 8}[level]
    global_cap = {1: 8, 2: 16, 3: 26, 4: 42, 5: 60}[level]

    notice = (
        "> ⚠️ **本地摘录模式**：未配置大模型 API，以下内容由课件原文抽取与压缩而成，"
        "不做翻译，质量低于 AI 笔记。配置 API Key 后可获得改写、双语和分级详讲的笔记。"
    )
    if reason:
        notice += f"\n> \n> 原因：{reason}"

    slides = doc.get("slides", [])
    noise_lines = _deck_noise_lines(slides)
    body_chunks: list[str] = []
    section_summaries: list[tuple[str, str]] = []
    produced = 0
    seen: set[str] = set()

    for slide_position, slide in enumerate(slides):
        if produced >= global_cap:
            break
        remaining_slides = max(1, len(slides) - slide_position)
        budget_left = global_cap - produced
        title = (slide.get("title") or "").strip()
        if title.strip().lower() in SKIP_TITLES or is_admin_heading(title):
            continue
        raw = strip_admin_lines((slide.get("text") or "").strip())
        if not raw:
            continue
        raw_lines = [line for line in raw.splitlines() if line.strip()]
        if _looks_like_cover(slide, len(raw_lines)):
            continue
        title_key = _normalize(title)
        candidates: list[tuple[float, str, int]] = []
        for position, sentence in enumerate(_split_sentences(raw)):
            sentence = _clean_sentence(sentence)
            key = _normalize(sentence)
            if len(key) < 6 or key in seen or key == title_key:
                continue
            if key in noise_lines or _is_layout_noise(sentence) or is_admin_text(sentence):
                continue
            seen.add(key)
            score = _score_sentence(sentence, title, position)
            candidates.append((score, sentence, position))

        # Table rows are converted into a dedicated table component below.
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[2]))
        take = min(
            max_per_slide,
            max(1, math.ceil(budget_left / remaining_slides)),
        )
        chosen = candidates[:take]
        if not chosen:
            continue
        chosen.sort(key=lambda item: item[2])
        if level == 1:
            chosen = chosen[:2]
            core_threshold = chosen[0][0]
        else:
            scores = sorted((c[0] for c in chosen), reverse=True)
            core_threshold = scores[max(0, min(len(scores) - 1, math.ceil(len(scores) * 0.3) - 1))]
            key_threshold = scores[max(0, min(len(scores) - 1, math.ceil(len(scores) * 0.7) - 1))]

        lines: list[str] = []
        for score, sentence, _ in chosen:
            if produced >= global_cap:
                break
            if level <= 2:
                tag = "核心" if score >= core_threshold else "重点"
            elif score >= core_threshold:
                tag = "核心"
            elif score >= key_threshold:
                tag = "重点"
            else:
                tag = "了解"
            for fragment in _fragment_sentence(sentence, level):
                if produced >= global_cap:
                    break
                lines.append(f"- [{tag}] {fragment}")
                produced += 1
        if not lines:
            continue
        heading = title or "本页要点"
        content_visual = any(
            visual.get("kind") == "image" and float(visual.get("confidence") or 0) >= 0.8
            for visual in (slide.get("visuals") or [])
        )
        marker = "[[VISUAL p.{}]]\n".format(slide["index"]) if content_visual else ""
        combined = " ".join(lines)
        latin_chars = len(re.findall(r"[A-Za-z]", combined))
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", combined))
        english_section = latin_chars > cjk_chars * 2
        parallel = len(lines) >= 3 and (
            any(cue in title or cue in title.lower() for cue in PARALLEL_CUES)
            or english_section
        )
        if parallel:
            points = ":::branches\n" + "\n".join(lines) + "\n:::"
        else:
            points = "\n".join(lines)
        chunk = f"## {heading} [p.{slide['index']}]\n{marker}" + points
        table_blocks = [
            _table_block(element, (title + " · 对比表") if title else "对比表")
            for element in slide.get("preview", {}).get("elements", [])
            if element.get("type") == "table"
        ]
        table_blocks = [block for block in table_blocks if block]
        if table_blocks:
            chunk += "\n\n" + "\n\n".join(table_blocks)
        body_chunks.append(chunk)
        first_point = lines[0][2:] if lines[0].startswith("- ") else lines[0]
        first_point = re.sub(r"^\[(核心|重点|了解)\]\s*", "", first_point)
        section_summaries.append((heading, first_point[:70]))

    if not body_chunks:
        return (
            notice
            + "\n\n## 未能提取到知识点\n\n课件中没有足够的文字内容，请检查是否为扫描版 PDF。"
        )

    title = {
        "en": "Extractive notes (local mode)",
        "bilingual": "课件摘录 / Extractive notes",
    }.get(language, "课件摘录笔记")
    overview = ""
    if level >= 3 and len(section_summaries) >= 3:
        map_lines = [":::mindmap 本讲知识地图"]
        for section_title, first_point in section_summaries[:6]:
            map_lines.append(f"- {section_title}")
            map_lines.append(f"  - {first_point}")
        map_lines.append(":::")
        overview = "\n".join(map_lines) + "\n\n"
    return f"# {title}\n\n{notice}\n\n{overview}" + "\n\n".join(body_chunks)
