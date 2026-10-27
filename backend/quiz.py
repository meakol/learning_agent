from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR, settings
from .llm import LLMConfig, complete_chat
from .prompts import load
from .text_utils import (
    extract_json,
    is_admin_text,
    is_meta_question,
    longest_common_substring,
    normalize_text,
    strip_admin_lines,
)

QUIZ_ID_RE = re.compile(r"^quiz_[a-f0-9]{12}$")
_BANNED_CORRECT = {"以上都不是", "以上都对", "全部正确", "以上皆非"}
_SENTENCE_RE = re.compile(r"(?<=[。！？；!?;])\s*|(?<=\.)\s+")
_PAGE_MARK_RE = re.compile(r"\[\s*p\.\s*\d+", re.IGNORECASE)
_PAGE_WORD_RE = re.compile(r"第\s*\d+\s*页")
_LANGUAGE_RULES = {
    "zh": (
        "所有题干、选项、提示与解释一律使用简体中文（专业术语可保留英文原文）。"
        "题干与选项不得出现页码；解释末尾用 [p.页码] 标注依据页。"
    ),
    "en": (
        "Write every question stem, option and hint in English (technical terms may keep "
        "their original spelling). Never put page numbers in the stem or options. In the "
        "explanation, reason in English and end with a page marker such as [p.3]; you may "
        "quote the slide wording once, in its original language, inside quotation marks so "
        "the answer stays traceable."
    ),
}
# Applied questions get roughly 40% of the paper so quizzes are not pure recall.
APPLY_RATIO = 0.4
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’_-]*")
_GENERIC_STEM_RE = re.compile(
    r"^(?:以下|下列|如下|下面)(?:的)?(?:哪项|哪个|哪一项|哪一种|哪种|哪些)"
    r"(?:说法|表述|描述|选项|判断)?(?:是|为)?(?:正确|错误|不对|不正确|最恰当|最合适)的?(?:是)?[？?。]?$"
    r"|^which of the following(?: statements?| options?| choices?)?"
    r"(?: is| are)?(?: correct| true| false| wrong| incorrect| the best)?[？?]?$",
    re.IGNORECASE,
)



def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def quiz_path(doc_id: str, quiz_id: str) -> Path:
    return DATA_DIR / doc_id / "quizzes" / f"{quiz_id}.json"


def find_quiz(quiz_id: str) -> dict[str, Any] | None:
    if not QUIZ_ID_RE.match(quiz_id or ""):
        return None
    for doc_dir in DATA_DIR.iterdir():
        if not doc_dir.is_dir():
            continue
        path = doc_dir / "quizzes" / f"{quiz_id}.json"
        if path.is_file():
            return _read(path)
    return None


def _page_texts(doc: dict[str, Any], pages: set[int]) -> dict[int, str]:
    """Return admin-free text per page; course logistics never reaches the model."""
    result: dict[int, str] = {}
    for slide in doc.get("slides", []):
        page = int(slide.get("index") or 0)
        if page not in pages:
            continue
        raw = "\n".join(
            part
            for part in ((slide.get("title") or "").strip(), (slide.get("text") or "").strip())
            if part
        )
        cleaned = strip_admin_lines(raw)
        if cleaned:
            result[page] = cleaned
    return result


def _options(raw: Any) -> list[str]:
    values = [str(item).strip() for item in (raw or []) if str(item).strip()]
    if len(values) != 4:
        return []
    result = []
    for index, value in enumerate(values):
        prefix = f"{'ABCD'[index]}."
        value = re.sub(r"^[A-Da-d][.、]\s*", "", value).strip()
        result.append(f"{prefix} {value}")
    return result


def required_apply_count(count: int) -> int:
    """How many questions should be applied/scenario style."""
    if count <= 1:
        return 1
    return max(1, min(count - 1, round(count * APPLY_RATIO)))


def _language_ok(text: str, language: str) -> bool:
    """Reject a Chinese paper written in English (or the reverse).

    Technical terms may stay in their original language, so the check only
    fires when a whole clause was written in the wrong language.
    """
    value = str(text or "")
    cjk = len(_CJK_RE.findall(value))
    words = len(_WORD_RE.findall(value))
    if language == "en":
        return words >= 2 and cjk <= max(4, words * 2)
    return not (cjk == 0 and words >= 4)


def _explanation_traces_source(explanation: str, source_text: str, language: str) -> bool:
    """The explanation must be traceable to the pages it claims to cite."""
    if len(longest_common_substring(explanation, source_text)) >= 8:
        return True
    if language != "en":
        return False
    # English explanations reason in English; a page marker is the minimum proof.
    return bool(_PAGE_MARK_RE.search(explanation)) and len(explanation) >= 30


def validate_question(
    question: dict[str, Any],
    texts: dict[int, str],
    start: int,
    end: int,
    difficulty: str,
    language: str = "zh",
) -> tuple[bool, str]:
    language = language if language in _LANGUAGE_RULES else "zh"
    text = str(question.get("question_text") or "").strip()
    if not 8 <= len(text) <= 300:
        return False, "题干长度"
    if is_admin_text(text):
        return False, "课程事务题干"
    if is_meta_question(text) or _PAGE_MARK_RE.search(text) or _PAGE_WORD_RE.search(text):
        return False, "元问题题干"
    if _GENERIC_STEM_RE.match(text):
        return False, "空泛题干"
    if not _language_ok(text, language):
        return False, "题干语言不符"
    options = _options(question.get("options"))
    if not options or len({normalize_text(item) for item in options}) != 4:
        return False, "选项"
    for option in options:
        body = option.split(".", 1)[-1]
        if is_admin_text(body) or is_meta_question(body):
            return False, "课程事务选项"
        if not _language_ok(body, language):
            return False, "选项语言不符"
    correct = str(question.get("correct_answer") or "").strip().upper()
    if correct not in "ABCD" or len(correct) != 1:
        return False, "答案"
    correct_body = options["ABCD".index(correct)].split(".", 1)[-1]
    if normalize_text(correct_body) in {normalize_text(item) for item in _BANNED_CORRECT}:
        return False, "禁用答案"
    pages = [int(page) for page in question.get("source_pages") or []]
    if not pages or any(page < start or page > end for page in pages):
        return False, "来源页"
    hint = str(question.get("hint") or "").strip()
    hint_limit = 120 if language == "en" else 80
    if not 1 <= len(hint) <= hint_limit:
        return False, "提示长度"
    if is_admin_text(hint) or is_meta_question(hint) or not _language_ok(hint, language):
        return False, "课程事务提示"
    if normalize_text(correct_body) in normalize_text(hint):
        return False, "提示泄露答案"
    explanation = str(question.get("explanation") or "").strip()
    explanation_limit = 600 if language == "en" else 400
    if not 1 <= len(explanation) <= explanation_limit:
        return False, "解释长度"
    if is_admin_text(explanation):
        return False, "课程事务解释"
    source_text = "\n".join(texts.get(page, "") for page in pages)
    if not _explanation_traces_source(explanation, source_text, language):
        return False, "解释未引用原文"
    if str(question.get("difficulty") or "") != difficulty:
        return False, "难度"
    return True, ""


def _select_questions(
    questions: list[dict[str, Any]], count: int, apply_count: int
) -> list[dict[str, Any]]:
    """Trim to ``count`` while keeping the applied/concept mix and source order."""
    order = {id(item): index for index, item in enumerate(questions)}
    applied = [item for item in questions if item.get("question_type") == "apply"]
    others = [item for item in questions if item.get("question_type") != "apply"]
    applied = applied[:apply_count]
    chosen = applied + others[: max(0, count - len(applied))]
    return sorted(chosen[:count], key=lambda item: order[id(item)])


def sanitize_quiz(quiz: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in quiz.items()
        if key not in {"questions", "result"}
    }
    result["questions"] = [
        {
            "question_id": item["question_id"],
            "question_text": item["question_text"],
            "options": item["options"],
            "hint": item.get("hint", ""),
            "source_pages": item.get("source_pages", []),
            "difficulty": item.get("difficulty", "medium"),
            "question_type": item.get("question_type", "recall"),
        }
        for item in quiz.get("questions", [])
    ]
    return result


def _body_texts(doc: dict[str, Any], pages: set[int]) -> dict[int, str]:
    """Knowledge-only slide bodies (no titles) for the extractive fallback."""
    result: dict[int, str] = {}
    for slide in doc.get("slides", []):
        page = int(slide.get("index") or 0)
        if page not in pages:
            continue
        cleaned = strip_admin_lines((slide.get("text") or "").strip())
        if cleaned:
            result[page] = cleaned
    return result


def _sentences(text: str) -> list[str]:
    """Split page text into sentences that look like statements, not labels."""
    result: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip(" \t-*•·")
        if not line or is_admin_text(line) or is_meta_question(line):
            continue
        for piece in _SENTENCE_RE.split(line):
            piece = piece.strip(" \t-*•·")
            if not 12 <= len(piece) <= 70:
                continue
            if is_admin_text(piece) or is_meta_question(piece):
                continue
            # Footers, slide labels and section headings carry no predicate: only keep
            # real statements (or long English sentences that omit the final period).
            if piece[-1] not in "。！？!?；;":
                if len(_WORD_RE.findall(piece)) < 8:
                    continue
            result.append(piece)
    return result


def _clip(text: str, limit: int = 60) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def fallback_questions(
    doc: dict[str, Any],
    pages: set[int],
    count: int = 5,
    difficulty: str = "medium",
    language: str = "zh",
) -> list[dict[str, Any]]:
    """Extractive fallback: ask which statement matches the slides.

    It never asks "what is this milestone about", and it returns fewer (or zero)
    questions instead of inventing filler options.
    """
    pool: list[tuple[int, str]] = []
    for page, text in sorted(_body_texts(doc, pages).items()):
        for sentence in _sentences(text):
            pool.append((page, sentence))
    if len(pool) < 4:
        return []

    questions: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, (page, sentence) in enumerate(pool):
        if len(questions) >= count:
            break
        correct_text = _clip(sentence)
        if correct_text in used or normalize_text(correct_text) in {
            normalize_text(item) for item in used
        }:
            continue
        distractors: list[str] = []
        for other_index, (_, other) in enumerate(pool):
            if other_index == index:
                continue
            candidate = _clip(other)
            if candidate == correct_text or candidate in distractors:
                continue
            if normalize_text(candidate) == normalize_text(correct_text):
                continue
            distractors.append(candidate)
            if len(distractors) == 3:
                break
        if len(distractors) < 3:
            break
        used.add(correct_text)
        position = len(questions) % 4
        values = distractors[:]
        values.insert(position, correct_text)
        stems_zh = (
            "下列哪一项符合课件中的表述？",
            "根据给定内容，下列判断正确的是？",
            "以下哪一项与材料一致？",
        )
        stems_en = (
            "Which statement matches the slide content?",
            "Which of the following is supported by the material?",
            "Which claim agrees with the slides?",
        )
        stems = stems_en if language == "en" else stems_zh
        questions.append(
            {
                "question_text": stems[len(questions) % len(stems)],
                "options": [f"{'ABCD'[i]}. {value}" for i, value in enumerate(values)],
                "correct_answer": "ABCD"[position],
                "hint": (
                    "Review the page that contains this wording."
                    if language == "en"
                    else "回看包含该表述的页面。"
                ),
                "explanation": f"{sentence} [p.{page}]",
                "source_pages": [page],
                "difficulty": difficulty,
                "question_type": "recall",
            }
        )
    return questions


def list_for_doc(doc_id: str, signature: str | None = None) -> list[dict[str, Any]]:
    """Return every quiz attempt for a document (or one notes variant), newest first."""
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return []
    candidates = []
    for path in folder.glob("*.json"):
        data = _read(path)
        if not data:
            continue
        if signature and data.get("signature") != signature:
            continue
        candidates.append(data)
    return sorted(candidates, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def latest_for_doc(
    doc_id: str,
    signature: str,
    preferred_quiz_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the quiz to recover after refresh, preferring the submitted one."""
    candidates = list_for_doc(doc_id, signature)
    if not candidates:
        return None
    if preferred_quiz_id:
        for item in candidates:
            if item.get("quiz_id") == preferred_quiz_id:
                return item
    ready = [
        item
        for item in candidates
        if item.get("status") == "ready" and item.get("source") != "fallback"
    ]
    pool = ready or [item for item in candidates if item.get("status") == "ready"] or candidates
    return max(pool, key=lambda item: str(item.get("created_at") or ""))


def _cache_match(
    doc_id: str,
    signature: str,
    section_ids: list[str],
    difficulty: str,
    count: int,
    language: str = "zh",
) -> dict[str, Any] | None:
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return None
    wanted = sorted(set(section_ids))
    for path in folder.glob("*.json"):
        data = _read(path)
        if not data or data.get("status") != "ready":
            continue
        if data.get("signature") != signature:
            continue
        if sorted(set(data.get("section_ids") or [])) != wanted:
            continue
        if data.get("difficulty") != difficulty:
            continue
        if int(data.get("question_count_requested") or 0) != count:
            continue
        if (data.get("language") or "zh") != language:
            continue
        return data
    return None


def save_result(quiz: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Store the graded result next to the quiz so history survives refresh."""
    data = dict(quiz)
    data["result"] = result
    data["result_at"] = _now()
    _write(quiz_path(data["doc_id"], data["quiz_id"]), data)
    return data


async def generate_quiz(
    doc: dict[str, Any],
    sections: list[dict[str, Any]],
    signature: str,
    count: int = 5,
    difficulty: str = "medium",
    language: str = "zh",
    api: LLMConfig | None = None,
    force: bool = False,
    force_fallback: bool = False,
) -> dict[str, Any]:
    doc_id = doc["doc_id"]
    section_ids = [item["section_id"] for item in sections]
    section_titles = [item.get("title") or "" for item in sections]
    pages = {int(page) for item in sections for page in item.get("pages") or []}
    page_start = min(pages) if pages else 1
    page_end = max(pages) if pages else 0
    language = language if language in _LANGUAGE_RULES else "zh"
    apply_count = required_apply_count(count)
    if not force:
        cached = _cache_match(doc_id, signature, section_ids, difficulty, count, language)
        # Do not keep serving a fallback quiz after the user configures a model.
        if cached and (cached.get("source") != "fallback" or api is None or not api.api_key):
            return cached

    texts = _page_texts(doc, pages)
    raw_text = "\n".join(
        f"<<< 第 {page} 页 >>>\n{text}" for page, text in sorted(texts.items())
    ).strip()
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []
    source = "llm"

    if force_fallback or api is None or not api.api_key or len(raw_text) < 80:
        source = "fallback"
        if len(raw_text) < 20:
            warnings.append("所选章节文本过少，无法出题。")
        else:
            questions = fallback_questions(doc, pages, count, difficulty, language)
            warnings.append(
                "使用课件原文比对题；内容不足或未配置模型。"
                if questions
                else "内容不足，未能生成有效题目。"
            )
    else:
        base_user = (
            f"章节：{'；'.join(section_titles)}\n"
            f"页面：{page_start}-{page_end}\n"
            f"难度：{difficulty}\n题数：{count}\n"
            f"应用题：{apply_count} 题（新情境/数据/案例，其余为概念辨析）\n"
            f"语言：{language}\n"
            f"内容：\n{raw_text[:6000]}"
        )
        last_error = ""
        for _ in range(3):
            user = base_user
            if last_error:
                user += f"\n\n上次输出未通过校验：{last_error}。请修正后重新输出完整 JSON。"
            try:
                text = await asyncio.wait_for(
                    complete_chat(
                        [
                            {
                                "role": "system",
                                "content": load(
                                    "quiz/system.md",
                                    language_rules=_LANGUAGE_RULES[language],
                                    count=count,
                                    apply_count=apply_count,
                                    difficulty=difficulty,
                                ),
                            },
                            {"role": "user", "content": user},
                        ],
                        api,
                        max_tokens=3600,
                        temperature=settings.quiz_temperature,
                        timeout=settings.quiz_timeout_seconds,
                    ),
                    timeout=settings.quiz_timeout_seconds + 2,
                )
                data = extract_json(text)
                if not isinstance(data, dict):
                    raise ValueError("题目 JSON 不是对象")
                validation_errors: list[str] = []
                seen = {
                    normalize_text(
                        item["options"]["ABCD".index(item["correct_answer"])].split(".", 1)[-1]
                    )
                    for item in questions
                }
                for item in data.get("questions") or []:
                    candidate = dict(item)
                    candidate["options"] = _options(candidate.get("options"))
                    candidate["question_type"] = (
                        "apply"
                        if str(candidate.get("question_type") or "").strip().lower() == "apply"
                        else "recall"
                    )
                    ok, reason = validate_question(
                        candidate, texts, page_start, page_end, difficulty, language
                    )
                    if not ok:
                        validation_errors.append(reason or "题目校验失败")
                        continue
                    key = normalize_text(
                        candidate["options"]["ABCD".index(candidate["correct_answer"])].split(".", 1)[-1]
                    )
                    if key in seen:
                        validation_errors.append("重复考点")
                        continue
                    seen.add(key)
                    questions.append(candidate)
                applied = sum(1 for item in questions if item.get("question_type") == "apply")
                if len(questions) >= count and applied >= apply_count:
                    break
                if len(questions) >= count:
                    last_error = f"应用题不足（目标 {apply_count} 题，实际 {applied} 题）"
                elif validation_errors:
                    last_error = "；".join(dict.fromkeys(validation_errors))[:160]
            except Exception as exc:
                last_error = str(exc).strip().replace("\n", " ")[:160] or type(exc).__name__
                continue

        if not questions:
            source = "fallback"
            questions = fallback_questions(doc, pages, count, difficulty, language)
            warning = "模型出题失败，改用课件原文比对题。"
            warnings.append(warning if questions else f"{warning}（内容不足）")
            if last_error:
                warnings.append(f"校验失败原因：{last_error}")
        else:
            if len(questions) < count:
                warnings.append(f"内容不足，实际生成 {len(questions)} 题。")
            applied = sum(1 for item in questions if item.get("question_type") == "apply")
            if applied < apply_count:
                warnings.append(f"应用题 {applied} 题，低于目标 {apply_count} 题。")

    if source == "fallback" and language == "en" and questions:
        warnings.append("英文题在本地比对模式下不翻译原文，选项沿用课件语言。")

    questions = _select_questions(questions, count, apply_count)
    for index, question in enumerate(questions, 1):
        question["question_id"] = f"q{index}"
    quiz_id = f"quiz_{uuid.uuid4().hex[:12]}"
    quiz = {
        "quiz_id": quiz_id,
        "doc_id": doc_id,
        "signature": signature,
        "section_ids": section_ids,
        "section_titles": section_titles,
        "language": language,
        "apply_count_requested": apply_count,
        "question_count_requested": count,
        "question_count_actual": len(questions),
        "difficulty": difficulty,
        "status": "ready" if questions else "empty",
        "questions": questions,
        "source": source,
        "warnings": warnings,
        "created_at": _now(),
    }
    _write(quiz_path(doc_id, quiz_id), quiz)
    return quiz


def grade_quiz(quiz: dict[str, Any], answers: list[dict[str, str]]) -> dict[str, Any]:
    if quiz.get("status") != "ready" or not quiz.get("questions"):
        raise ValueError("QUIZ_EMPTY")
    expected = [item["question_id"] for item in quiz["questions"]]
    submitted = {item.get("question_id"): str(item.get("selected", "")).upper() for item in answers}
    if len(submitted) != len(expected) or set(submitted) != set(expected):
        raise ValueError("INCOMPLETE_ANSWERS")
    if any(value not in "ABCD" or len(value) != 1 for value in submitted.values()):
        raise ValueError("INVALID_ANSWER")
    results = []
    correct_count = 0
    for item in quiz["questions"]:
        selected = submitted[item["question_id"]]
        correct = selected == item["correct_answer"]
        correct_count += int(correct)
        results.append(
            {
                "question_id": item["question_id"],
                "selected": selected,
                "correct_answer": item["correct_answer"],
                "correct": correct,
                "explanation": item.get("explanation", ""),
                "source_pages": item.get("source_pages", []),
            }
        )
    return {
        "quiz_id": quiz["quiz_id"],
        "section_ids": quiz.get("section_ids", []),
        "section_titles": quiz.get("section_titles", []),
        "score": round(correct_count / len(expected), 4),
        "correct_count": correct_count,
        "total_count": len(expected),
        "results": results,
        "completed_at": _now(),
    }

