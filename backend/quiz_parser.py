import json
import re
import random
from typing import Optional
import os
from fastapi import HTTPException

BAD_TF_STARTERS = (
    "what ", "which ", "who ", "how ", "when ", "where ", "why ",
    "describe ", "explain ", "list ", "name ", "give ", "define ",
)

MAX_DOC_CHARS: int = int(os.getenv("MAX_DOC_CHARS", "8000"))
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))


def build_prompt(doc_text: str, num_questions: int, question_type: str, difficulty: str) -> str:
    if len(doc_text) > MAX_DOC_CHARS:
        truncated = doc_text[:MAX_DOC_CHARS]
    else:
        truncated = doc_text

    if question_type == "Multiple Choice":
        type_rules = (
            "Generate MULTIPLE CHOICE questions only.\n"
            "- Each question has EXACTLY 4 options (A, B, C, D).\n"
            "- 'answer' field = one letter: A, B, C, or D.\n"
            "- One correct option, three wrong but plausible options.\n"
            "- Questions start with: What, Which, Who, How, When, Where.\n"
            f"- You MUST generate EXACTLY {num_questions} questions.\n"
            f"- If you generate fewer, the output is INVALID.\n"
            "Do not stop early. Continue generating until all questions are completed.\n"
        )
        example = (
            '{"id":1,"type":"mcq","difficulty":"Easy","question":"Which language is used for backend?",'
            '"options":["Python","HTML","CSS","Photoshop"],"answer":"A"}'
        )

    elif question_type == "True / False":
        type_rules = (
            "Generate TRUE/FALSE questions only.\n"
            "CRITICAL RULE — Every question MUST be a DECLARATIVE STATEMENT, NOT a question.\n"
            "WRONG: 'What is the person email?' — This is a question!\n"
            "CORRECT: 'The candidate holds a Bachelor degree in Computer Science.' — answer: True\n"
            "- 'options' must always be exactly: ['True', 'False']\n"
            "- 'answer' must be exactly 'True' or 'False'\n"
            "- Statements must be verifiable from the text.\n"
            f"- You MUST generate EXACTLY {num_questions} questions.\n"
        )
        example = (
            '{"id":1,"type":"tf","difficulty":"Medium","question":"The candidate has completed a Bachelor\'s degree.",'
            '"options":["True","False"],"answer":"True"}'
        )


    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid question_type. Only 'Multiple Choice' or 'True / False' allowed."
        )

    easy  = max(1, num_questions // 3)
    hard  = max(1, num_questions // 3)
    medium = max(0, num_questions - easy - hard)

    diff_rule = (
        f"You MUST assign MIXED difficulty across ALL {num_questions} questions:\n"
        f"- EXACTLY {easy} question(s) labeled 'Easy'\n"
        f"- EXACTLY {medium} question(s) labeled 'Medium'\n"
        f"- EXACTLY {hard} question(s) labeled 'Hard'\n"
        f"Every question MUST have a 'difficulty' field set to one of: 'Easy', 'Medium', 'Hard'.\n"
        f"Do NOT assign the same difficulty to all questions.\n"
    )

    prompt = (
        f"You are a quiz generator. Read the text and generate exactly {num_questions} questions.\n\n"
        f"{diff_rule}\n"
        f"{type_rules}\n"
        f"Return ONLY valid JSON. No markdown, no explanation, no extra text.\n\n"
        f"JSON format:\n"
        f'{{"title":"Short quiz title","questions":[{example},...]}}\n\n'
        f"TEXT:\n\"\"\"\n{truncated}\n\"\"\"\n\n"
        f"JSON:"
    )
    return prompt


def parse_quiz_output(
    raw_text: str,
    requested: int = 0,
    question_type: str = "",
) -> Optional[dict]:
    text = raw_text.strip()

    quiz = None

    for fn in [
        _try_direct_parse,
        _strip_markdown_and_parse,
        _slice_from_title,
        _extract_questions_via_decoder,
    ]:
        candidate = fn(text)
        if candidate:
            quiz = candidate
            break

    if not quiz:
        print("Failed to parse LLM output")
        print("---- RAW OUTPUT START ----")
        print(raw_text[:1000])
        print("---- RAW OUTPUT END ----")
        return None

    if not isinstance(quiz, dict) or not isinstance(quiz.get("questions"), list):
        print("Invalid quiz structure")
        return None

    return _normalize(quiz, question_type, requested)



def _try_direct_parse(text: str) -> Optional[dict]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "questions" in obj:
            return obj
    except Exception:
        pass
    return None


def _strip_markdown_and_parse(text: str) -> Optional[dict]:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    return _try_direct_parse(cleaned)


def _slice_from_title(text: str) -> Optional[dict]:
    for marker in ['{"title"', '{ "title"']:
        idx = text.find(marker)
        if idx >= 0:
            end = text.rfind('}')
            if end > idx:
                candidate = text[idx:end + 1]
                result = _try_direct_parse(candidate)
                if result:
                    return result
    return None


def _extract_questions_via_decoder(text: str) -> Optional[dict]:
    decoder = json.JSONDecoder()

    title_match = re.search(r'"title"\s*:\s*"([^"]*)"', text)
    title = title_match.group(1) if title_match else "Quiz"

    questions = []
    seen_ids = set()
    for match in re.finditer(r'\{\s*"id"\s*:', text):
        pos = match.start()
        try:
            obj, _ = decoder.raw_decode(text, pos)
            if (
                isinstance(obj, dict)
                and "question" in obj
                and obj.get("id") not in seen_ids
            ):
                seen_ids.add(obj.get("id"))
                questions.append(obj)
        except json.JSONDecodeError:
            pass

    if not questions:
        return None

    return {"title": title, "questions": questions}


def _normalize(quiz: dict, question_type: str = "", requested: int = 0) -> dict:
    questions = quiz.get("questions", [])
    if not questions:
        return {"title": quiz.get("title", "Quiz"), "questions": []}
    normalized = []

    for i, q in enumerate(questions):
        if not isinstance(q, dict) or not q.get("question"):
            continue

        qtype      = str(q.get("type", "mcq")).lower().strip()
        q_val = q.get("question", "")

        if isinstance(q_val, dict):
            q_val = q_val.get("text", "")
        elif isinstance(q_val, list):
            q_val = " ".join(str(v) for v in q_val)

        question = str(q_val).strip()
        options    = list(q.get("options") or [])
        answer     = str(q.get("answer", "")).strip()
        difficulty = str(q.get("difficulty", "")).strip()

        if difficulty not in ("Easy", "Medium", "Hard"):
            difficulty = ""

        if qtype == "tf" and any(question.lower().startswith(s) for s in BAD_TF_STARTERS):
            continue

        if qtype == "mcq":
            if not options or len(options) < 2:
                continue
            while len(options) < 4:
                options.append("None of the above")
            options = options[:4]

            if answer not in ("A", "B", "C", "D"):
                matched = False
                ans_clean = answer.lower().strip()

                for idx, opt in enumerate(options):
                    if ans_clean == opt.lower().strip():
                        answer = chr(65 + idx)
                        matched = True
                        break

                if not matched:
                    continue
        elif qtype == "tf":
            options = ["True", "False"]
            if answer.lower() in ("true", "1", "yes", "correct"):
                answer = "True"
            elif answer.lower() in ("false", "0", "no", "incorrect"):
                answer = "False"
            else:
                continue

        else:
            continue

        normalized.append({
            "id":         i + 1,
            "type":       qtype,
            "difficulty": difficulty,
            "question":   question,
            "options":    options,
            "answer":     answer,
        })

    for idx, q in enumerate(normalized):
        q["id"] = idx + 1

    normalized = _enforce_difficulty_distribution(normalized)

    seen = set()
    deduped = []

    for q in normalized:
        key = q["question"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(q)

    normalized = deduped

    normalized = [
        q for q in normalized
        if q.get("question") and q.get("answer") and q.get("options")
    ]

    if requested > 0:
        normalized = normalized[:requested]

    return {
        "title":     str(quiz.get("title", "Quiz")).strip(),
        "questions": normalized,
    }


def _enforce_difficulty_distribution(questions: list) -> list:
    if not questions:
        return questions

    n = len(questions)
    targets = _difficulty_targets(n)

    unset   = [q for q in questions if not q["difficulty"]]
    preset  = [q for q in questions if q["difficulty"]]

    counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    for q in preset:
        counts[q["difficulty"]] += 1

    pool = []
    for level in ("Easy", "Medium", "Hard"):
        need = max(0, targets[level] - counts[level])
        pool.extend([level] * need)

    while len(pool) < len(unset):
        pool.append("Medium")

    random.shuffle(pool)

    for q, level in zip(unset, pool):
        q["difficulty"] = level

    final_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    for q in questions:
        final_counts[q["difficulty"]] += 1

    dominated = any(v == n for v in final_counts.values())
    if dominated and n >= 3:
        all_levels = (
            ["Easy"]   * targets["Easy"] +
            ["Medium"] * targets["Medium"] +
            ["Hard"]   * targets["Hard"]
        )
        while len(all_levels) < n:
            all_levels.append("Medium")
        random.shuffle(all_levels)
        for q, level in zip(questions, all_levels):
            q["difficulty"] = level

    return questions


def _difficulty_targets(n: int) -> dict:
    if n <= 0:
        return {"Easy": 0, "Medium": 0, "Hard": 0}
    if n == 1:
        return {"Easy": 0, "Medium": 1, "Hard": 0}
    if n == 2:
        return {"Easy": 1, "Medium": 0, "Hard": 1}
    easy   = max(1, n // 3)
    hard   = max(1, n // 3)
    medium = n - easy - hard
    while medium < 0:
        hard  -= 1
        medium = n - easy - hard
    return {"Easy": easy, "Medium": max(0, medium), "Hard": hard}