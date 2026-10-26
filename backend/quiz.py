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
from .progress import add_quiz_result
from .prompts import load
from .text_utils import extract_json, longest_common_substring, normalize_text

QUIZ_ID_RE = re.compile(r"^quiz_[a-f0-9]{12}$")
_BANNED_CORRECT = {"以上都不是", "以上都对", "全部正确", "以上皆非"}


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


def _page_texts(doc: dict[str, Any], start: int, end: int) -> dict[int, str]:
    result = {}
    for slide in doc.get("slides", []):
        page = int(slide.get("index") or 0)
        if start <= page <= end:
            result[page] = (slide.get("text") or "") + "\n" + (slide.get("title") or "")
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


def validate_question(
    question: dict[str, Any],
    texts: dict[int, str],
    start: int,
    end: int,
    difficulty: str,
) -> tuple[bool, str]:
    text = str(question.get("question_text") or "").strip()
    if not 5 <= len(text) <= 200:
        return False, "题干长度"
    options = _options(question.get("options"))
    if not options or len({normalize_text(item) for item in options}) != 4:
        return False, "选项"
    correct = str(question.get("correct_answer") or "").strip().upper()
    if correct not in "ABCD" or len(correct) != 1:
        return False, "答案"
    correct_text = options["ABCD".index(correct)]
    if normalize_text(correct_text.split(".", 1)[-1]) in {normalize_text(item) for item in _BANNED_CORRECT}:
        return False, "禁用答案"
    pages = [int(page) for page in question.get("source_pages") or []]
    if not pages or any(page < start or page > end for page in pages):
        return False, "来源页"
    hint = str(question.get("hint") or "").strip()
    if not 1 <= len(hint) <= 80 or normalize_text(correct_text.split(".", 1)[-1]) in normalize_text(hint):
        return False, "提示"
    explanation = str(question.get("explanation") or "").strip()
    if not 1 <= len(explanation) <= 300:
        return False, "解释长度"
    source_text = "\n".join(texts.get(page, "") for page in pages)
    if len(longest_common_substring(explanation, source_text)) < 8:
        return False, "解释未引用原文"
    if str(question.get("difficulty") or "") != difficulty:
        return False, "难度"
    return True, ""


def sanitize_quiz(quiz: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in quiz.items() if key != "questions"}
    result["questions"] = [
        {
            "question_id": item["question_id"],
            "question_text": item["question_text"],
            "options": item["options"],
            "hint": item.get("hint", ""),
            "source_pages": item.get("source_pages", []),
            "difficulty": item.get("difficulty", "medium"),
        }
        for item in quiz.get("questions", [])
    ]
    return result


def fallback_questions(plan: dict[str, Any], milestone: dict[str, Any], count: int) -> list[dict[str, Any]]:
    title = milestone.get("title") or "本里程碑"
    other = [item.get("title") for item in plan.get("milestones", []) if item is not milestone and item.get("title")]
    page_titles = milestone.get("page_titles") or []
    distractors = other + [item for item in page_titles if item != title]
    distractors = [item for item in distractors if item and item != title][:3]
    while len(distractors) < 3:
        distractors.append(f"第 {milestone['page_range']['start']} 页的无关装饰文字 {len(distractors) + 1}")
    options = [f"A. {title}", f"B. {distractors[0]}", f"C. {distractors[1]}", f"D. {distractors[2]}"]
    return [
        {
            "question_id": "q1",
            "question_text": "以下哪一项最符合该里程碑的主题？",
            "options": options,
            "correct_answer": "A",
            "hint": "回看该里程碑的标题与第一页。",
            "explanation": f"该里程碑标题为“{title}”。[p.{milestone['page_range']['start']}]",
            "source_pages": [milestone["page_range"]["start"]],
            "difficulty": "easy",
        }
    ]


def list_for_plan(
    doc_id: str,
    plan_id: str,
    milestone_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return every quiz attempt for a plan, newest first."""
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return []
    candidates = []
    for path in folder.glob("*.json"):
        data = _read(path)
        if not data or data.get("plan_id") != plan_id:
            continue
        if milestone_id and data.get("milestone_id") != milestone_id:
            continue
        candidates.append(data)
    return sorted(candidates, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def latest_for_milestone(
    doc_id: str,
    plan_id: str,
    milestone_id: str,
    preferred_quiz_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the quiz to recover after refresh, preferring the submitted one."""
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return None
    candidates = []
    for path in folder.glob("*.json"):
        data = _read(path)
        if (
            data
            and data.get("plan_id") == plan_id
            and data.get("milestone_id") == milestone_id
        ):
            candidates.append(data)
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
    doc_id: str, plan_id: str, milestone_id: str, difficulty: str, count: int
) -> dict[str, Any] | None:
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return None
    for path in folder.glob("*.json"):
        data = _read(path)
        if (
            data
            and data.get("status") == "ready"
            and data.get("plan_id") == plan_id
            and data.get("milestone_id") == milestone_id
            and data.get("difficulty") == difficulty
            and int(data.get("question_count_requested") or 0) == count
        ):
            return data
    return None

async def generate_quiz(
    doc: dict[str, Any],
    plan: dict[str, Any],
    milestone: dict[str, Any],
    count: int = 5,
    difficulty: str = "medium",
    api: LLMConfig | None = None,
    force: bool = False,
    force_fallback: bool = False,
) -> dict[str, Any]:
    doc_id = doc["doc_id"]
    plan_id = plan["plan_id"]
    milestone_id = milestone["milestone_id"]
    if not force:
        cached = _cache_match(doc_id, plan_id, milestone_id, difficulty, count)
        # Do not keep serving a fallback quiz after the user configures a model.
        if cached and (cached.get("source") != "fallback" or api is None or not api.api_key):
            return cached

    start = int(milestone["page_range"]["start"])
    end = int(milestone["page_range"]["end"])
    texts = _page_texts(doc, start, end)
    raw_text = "\n".join(texts.values()).strip()
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []
    source = "llm"

    if force_fallback or api is None or not api.api_key or len(raw_text) < 200:
        source = "fallback"
        if len(raw_text) < 20:
            warnings.append("里程碑内容过少，无法出题。")
        else:
            questions = fallback_questions(plan, milestone, count)
            warnings.append("使用标题回忆题；内容不足或未配置模型。")
    else:
        base_user = (
            f"里程碑：{milestone.get('title', '')}\n"
            f"页面：{start}-{end}\n难度：{difficulty}\n题数：{count}\n"
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
                            {"role": "system", "content": load("quiz/system.md")},
                            {"role": "user", "content": user},
                        ],
                        api,
                        max_tokens=3000,
                        temperature=0.3,
                        timeout=settings.quiz_timeout_seconds,
                    ),
                    timeout=settings.quiz_timeout_seconds + 2,
                )
                data = extract_json(text)
                if not isinstance(data, dict):
                    raise ValueError("题目 JSON 不是对象")
                validation_errors: list[str] = []
                for item in data.get("questions") or []:
                    candidate = dict(item)
                    candidate["options"] = _options(candidate.get("options"))
                    ok, reason = validate_question(candidate, texts, start, end, difficulty)
                    if ok:
                        questions.append(candidate)
                    else:
                        validation_errors.append(reason or "题目校验失败")
                    if len(questions) >= count:
                        break
                if questions:
                    break
                if validation_errors:
                    last_error = "；".join(dict.fromkeys(validation_errors))[:160]
            except Exception as exc:
                last_error = str(exc).strip().replace("\n", " ")[:160] or type(exc).__name__
                continue

        if not questions:
            source = "fallback"
            questions = fallback_questions(plan, milestone, count)
            warning = "模型出题失败，使用标题回忆题。"
            if last_error:
                warning += f"（{last_error}）"
            warnings.append(warning)
        elif len(questions) < count:
            warnings.append(f"内容不足，实际生成 {len(questions)} 题。")

    questions = questions[:count]
    for index, question in enumerate(questions, 1):
        question["question_id"] = f"q{index}"
    quiz_id = f"quiz_{uuid.uuid4().hex[:12]}"
    quiz = {
        "quiz_id": quiz_id,
        "doc_id": doc_id,
        "plan_id": plan_id,
        "milestone_id": milestone_id,
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
        "milestone_id": quiz["milestone_id"],
        "score": round(correct_count / len(expected), 4),
        "correct_count": correct_count,
        "total_count": len(expected),
        "results": results,
        "completed_at": _now(),
    }


def delete_for_plan(doc_id: str, plan_id: str) -> None:
    folder = DATA_DIR / doc_id / "quizzes"
    if not folder.is_dir():
        return
    for path in folder.glob("*.json"):
        data = _read(path)
        if data and data.get("plan_id") == plan_id:
            path.unlink()

