from __future__ import annotations

import json
import re
from typing import Any, Iterable

_SENTENCE_RE = re.compile(r"(?<=[。！？；!?;])\s*|(?<=\.)\s+")
_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def estimate_tokens(chars: int) -> int:
    """Approximate mixed Chinese/English tokens used by the current project."""
    return max(1, round(max(0, chars) / 1.7))


def split_sentences(text: str) -> list[str]:
    """Split text into non-empty sentences without changing their order."""
    result: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip(" \t•·-–—*")
        if not line:
            continue
        for piece in _SENTENCE_RE.split(line):
            piece = piece.strip()
            if piece:
                result.append(piece)
    return result


def split_paragraphs(text: str, max_sentences: int = 3) -> list[str]:
    """Split long paragraphs at sentence boundaries, keeping short ones intact."""
    if max_sentences < 1:
        raise ValueError("max_sentences 必须 >= 1")
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", str(text or "")):
        block = block.strip()
        if not block:
            continue
        sentences = split_sentences(block)
        if len(sentences) <= max_sentences:
            paragraphs.append(block)
            continue
        for index in range(0, len(sentences), max_sentences):
            paragraphs.append("".join(sentences[index:index + max_sentences]))
    return paragraphs


def strip_banned_phrases(text: str, phrases: Iterable[str]) -> str:
    """Remove configured filler phrases and tidy resulting punctuation."""
    result = str(text or "")
    for phrase in sorted({p for p in phrases if p}, key=len, reverse=True):
        result = result.replace(phrase, "")
    result = re.sub(r"[，,]\s*[，,]+", "，", result)
    result = re.sub(r"([。！？；])[。！？；]+", r"\1", result)
    result = _SPACE_RE.sub(" ", result)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    return result


# Course logistics (schedule, grading, exams, contacts) is not subject knowledge.
_ADMIN_STRONG_PATTERNS = (
    r"课程(?:安排|计划|大纲|进度|日历|信息|须知)",
    r"教学(?:安排|计划|大纲|进度|日历)",
    r"(?:考核|评分|评价|打分)(?:方式|标准|办法|细则|构成|比例|规则)",
    r"(?:平时|期末|期中|结课)(?:成绩|考核|考试|测验|分数|占比)",
    r"成绩(?:构成|占比|比例|计算|评定)|及格(?:线|分)|绩点",
    r"(?:考试|测验|测试)(?:时间|日期|安排|范围|形式|题型|地点|要求)",
    r"(?:出勤|签到|点名|请假|调课|补课)",
    r"(?:作业|论文|报告|项目)(?:提交|截止|要求|格式)",
    r"(?:教材|参考书|参考文献|推荐阅读|必读书目|阅读材料)",
    r"(?:联系|答疑)(?:方式|时间|地点)|电子邮箱|邮箱地址|办公室|助教",
    r"课程(?:目标|要求|简介|介绍)",
    r"(?:考核|评分|打分|成绩|考试|测验)\s*[:：]",
    r"^(?:课程安排|课程计划|考核|考试|评分|成绩|作业|教材|参考书|课程目标|课程简介|打分)\s*[:：]?$",
    r"^(?:grading|assessment|evaluation|schedule|agenda|exams?|textbooks?|readings?|course (?:schedule|outline|objectives?|description))\s*$",
    r"(?:学分|平时分|课堂表现|出勤率|参考书目|课程材料)",
    r"(?:讲课|授课|任课)(?:教师|老师)|主讲教师",
    r"课程(?:概览|简介|介绍|说明|目标|要求|安排|计划|大纲|进度)",
    r"本课程(?:明确)?(?:不|将|会|主要)?(?:讨论|介绍|涵盖|包括|讲授|安排)",
    r"\b(?:course|lecture)\s+(?:plan|agenda|objectives?|materials?|overview)\b",
    r"\b(?:grading|assessment|evaluation)\s*[:：]",
    r"\b(?:course\s+credits?|GPA)\b",
    r"\b(?:instructor|lecturer|professor)\s+(?:name|contact|email|office)\b",

    r"\bsyllabus\b",
    r"\bcourse (?:schedule|outline|description|policy|logistics|information)\b",
    r"\b(?:grading|assessment|evaluation)\s+(?:policy|criteria|scheme|breakdown|rubric|method)\b",
    r"\b(?:final|midterm|make-?up)\s+(?:exam|test)\b",
    r"\bexam\s+(?:date|schedule|format|location|scope)\b",
    r"\b(?:attendance|roll call|office hours|teaching assistant)\b",
    r"\b(?:homework|assignment|report|project)\s+(?:submission|deadline|due date|format|requirements)\b",
    r"\b(?:required|recommended)\s+(?:textbook|reading)\b|\btextbook\b|\breading list\b",
    r"\b(?:instructor|lecturer)\s+(?:email|contact|office)\b",
)
# Weak cues are fine for a stray line, but too broad for headings such as
# "第 3 讲：注意力机制" which do carry the lecture topic.
_ADMIN_WEAK_PATTERNS = (
    r"(?:本周|下周|下次课|本次课|今天|今日)(?:的)?(?:安排|计划|内容|任务|主题|重点)",
    r"第\s*\d+\s*(?:周|讲|次课|单元)",
    r"\b(?:today|this week)'?s?\s+(?:agenda|plan|topic|schedule)\b",
    r"\blecture\s*\d+\b|\bweek\s*\d+\b",
)
_ADMIN_STRONG_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _ADMIN_STRONG_PATTERNS), re.IGNORECASE
)
_ADMIN_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _ADMIN_STRONG_PATTERNS + _ADMIN_WEAK_PATTERNS),
    re.IGNORECASE,
)

# Meta questions ask about the deck ("what did page 3 say?") instead of knowledge.
_META_QUESTION_PATTERNS = (
    r"第\s*(?:几|\d+)\s*页(?:主要)?(?:讲|说|介绍|提到|描述|列出|列|有)(?:了)?(?:什么|哪些|啥)",
    r"(?:本页|这页|该页|此页|上页|本讲|本节|本章|这一讲|这一章|本次课|这次课)"
    r"(?:主要)?(?:讲|说|介绍|提到|描述|列出|列|内容|主题)",
    r"(?:课件|幻灯片|PPT)(?:中|里|上)(?:主要)?(?:讲|说|介绍|提到|描述|列出)",
    r"(?:今天|今日|本次课|这次课|这堂课|本节课)(?:我们)?(?:学|讲|上|讨论|介绍)(?:了)?(?:什么|哪些|啥|内容)",
    r"(?:本|这)(?:讲|节|章|单元|课)(?:的)?(?:重点|内容|主题|目标|安排)(?:是|有|为)?(?:什么|哪些|啥)",
    r"主题(?:是|为)(?:什么|啥)|主要(?:内容|观点|思想)(?:是|为)?(?:什么|啥)",
    r"(?:课程|教学)(?:安排|计划|进度)(?:是|如何|怎么|什么)",
    r"\bwhich (?:page|slide)\b|\bwhat (?:did|does) (?:page|slide)\b",
    r"\bwhat (?:did|do|will) (?:we|you) (?:learn|cover|discuss|talk about)\b",
    r"\bwhat (?:is|was) (?:covered|taught|discussed|introduced|scheduled)\b",
    r"\bwhat(?:'s| is) the (?:topic|theme|main idea|focus) of (?:this|the) (?:lecture|chapter|section|course)\b",
    r"\bwhat (?:does|did) (?:this|the) (?:slide|page|lecture|chapter|section) (?:say|cover|discuss|introduce|mention)\b",
    r"\bwhat is this (?:lecture|chapter|section|slide) about\b|\bthe theme of this\b",
    r"\bthis (?:lecture|chapter|section|slide|page)\b",
)
_META_QUESTION_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _META_QUESTION_PATTERNS), re.IGNORECASE
)


def is_admin_text(text: str) -> bool:
    """True when a line or sentence is about course logistics instead of knowledge."""
    value = str(text or "").strip()
    if not value:
        return False
    return bool(_ADMIN_RE.search(value))


def is_admin_heading(text: str) -> bool:
    """True when a note/section title is course logistics (strong cues only)."""
    value = str(text or "").strip()
    if not value:
        return False
    return bool(_ADMIN_STRONG_RE.search(value))


def is_meta_question(text: str) -> bool:
    """True when a question asks about the slides rather than the subject."""
    value = str(text or "").strip()
    if not value:
        return False
    return bool(_META_QUESTION_RE.search(value))


def strip_admin_lines(text: str) -> str:
    """Drop lines that only carry course logistics while keeping the layout."""
    kept = [line for line in str(text or "").splitlines() if not is_admin_text(line)]
    return "\n".join(kept).strip()


def extract_json(text: str) -> Any:
    """Extract the first balanced JSON object/array from model prose or fences."""
    source = str(text or "").strip()
    source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.IGNORECASE).strip()
    start = min(
        (index for index in (source.find("{"), source.find("[")) if index >= 0),
        default=-1,
    )
    if start < 0:
        raise ValueError("模型没有返回 JSON。")
    opening = source[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return json.loads(source[start:index + 1])
    raise ValueError("模型返回的 JSON 不完整。")


def normalize_text(text: str) -> str:
    return re.sub(
        r"[\s，。！？；：、,.!?;:'\"“”‘’()（）\[\]【】]",
        "",
        str(text or ""),
    ).lower()


def longest_common_substring(left: str, right: str) -> str:
    """Return the longest common contiguous substring (used for quote checks)."""
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return ""
    previous = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, ch in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, 1):
            if ch == other:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    return a[best_end - best_len:best_end]


def slugify(value: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")
    return (slug or "default")[:max_length]
