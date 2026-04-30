from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
from contextlib import asynccontextmanager
import logging
from extractor import extract_text_from_file
from quiz_parser import parse_quiz_output, build_prompt
import sys
import os
import random



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


MAX_FILE_SIZE = 10 * 1024 * 1024

TOKEN_BUDGET = {
    "Multiple Choice": 280,
    "True / False":    180,
}
MAX_TOKENS_HARD_CAP = 8000


def calc_tokens(num_questions: int, question_type: str) -> int:
    per_q   = TOKEN_BUDGET.get(question_type, 280)
    buffer  = 600
    safe    = int(num_questions * per_q * 1.1) + buffer
    return min(MAX_TOKENS_HARD_CAP, safe)


def split_text(text: str, max_chunk_size: int = 3000):
    import re

    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) > max_chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""

        current += para + "\n\n"

    if current:
        chunks.append(current.strip())

    return chunks

def safe_json_load(output: str):
    import json

    try:
        return json.loads(output)
    except:
        last_brace = output.rfind("}")
        if last_brace != -1:
            try:
                return json.loads(output[:last_brace + 1])
            except:
                pass

    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Using Ollama server...")
    yield

from llm.ollama_client import OllamaClient

client = OllamaClient.get_instance()


async def check_ollama() -> bool:
    try:
        ollama = OllamaClient.get_instance()
        r = await ollama.async_client.get(f"{ollama.base_url}/api/tags")
        return r.status_code == 200
    except Exception:
        return False


app = FastAPI(
    title="QuizAI API",
    description="Generate quizzes from PDF/Word documents using a local open-source AI model.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/health")
async def health():

    return {
        "ollama_running": await check_ollama(),
        "model": client.model,
    }


@app.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE // (1024*1024)} MB.",
        )

    try:
        text = extract_text_from_file(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "filename":   file.filename,
        "word_count": len(text.split()),
        "char_count": len(text),
    }



@app.post("/generate-quiz")
async def generate_quiz(
    file: UploadFile = File(...),
    num_questions: int = Form(5),
    question_type: str = Form("Multiple Choice"),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        doc_text = extract_text_from_file(content, file.filename)
        chunks = split_text(doc_text)

        if len(chunks) > 1:
            chunks = chunks[1:]

        random.shuffle(chunks)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    max_tokens = calc_tokens(num_questions, question_type)

    from llm.ollama_client import OllamaClient

    client = OllamaClient.get_instance()

    try:
        questions = []
        used_questions = set()

        questions_per_chunk = max(1, min(
            num_questions // len(chunks) + (1 if num_questions % len(chunks) else 0),
            8
        ))
        global_id = 1


        for chunk in chunks:

            prompt = build_prompt(chunk, questions_per_chunk, question_type, "mixed_difficulty")

            output = await client.generate_async(prompt, max_tokens)

            output = output.strip().replace("```json", "").replace("```", "")

            quiz = None

            try:
                quiz = parse_quiz_output(output, questions_per_chunk, question_type)
            except Exception as e:
                logger.error(f"Quiz parsing failed: {e}")

                data = safe_json_load(output)
                if data and "questions" in data:
                    quiz = data


            if not quiz or not quiz.get("questions"):
                continue

            for q in quiz["questions"]:
                q_val = q.get("question", "")

                if isinstance(q_val, dict):
                    q_val = q_val.get("text", "")
                elif isinstance(q_val, list):
                    q_val = " ".join(map(str, q_val))

                q_text = str(q_val).strip().lower()

                if q_text not in used_questions:
                    q["id"] = global_id
                    global_id += 1

                    questions.append(q)
                    used_questions.add(q_text)

            if len(questions) >= num_questions:
                break

        questions = questions[:num_questions]

        if not questions:
            raise HTTPException(status_code=500, detail="Could not generate quiz")

        final_quiz = {
            "title": "Generated Quiz",
            "questions": questions
        }

        return {
            "success": True,
            "quiz": final_quiz,
            "tokens_used": max_tokens
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {str(e)}"
        )

@app.post("/generate-quiz-stream")
async def generate_quiz_stream(
    file: UploadFile = File(...),
    num_questions: int = Form(5),
    question_type: str = Form("Multiple Choice"),
    difficulty: str = Form("mixed_difficulty"),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        doc_text = extract_text_from_file(content, file.filename)
        chunks = split_text(doc_text)

        if len(chunks) > 1:
            chunks = chunks[1:]

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    MAX_Q_PER_CHUNK = 3

    chunks_needed = -(-num_questions // MAX_Q_PER_CHUNK)
    if len(chunks) < chunks_needed:
        smaller_chunks = split_text(doc_text, max_chunk_size=1500)
        if len(smaller_chunks) >= chunks_needed:
            chunks = smaller_chunks
        else:
            while len(chunks) < chunks_needed:
                chunks = chunks + chunks
            chunks = chunks[:chunks_needed]

    random.shuffle(chunks)


    max_tokens = calc_tokens(MAX_Q_PER_CHUNK, question_type)

    async def event_generator():
        questions = []
        used = set()

        from llm.ollama_client import OllamaClient
        client = OllamaClient.get_instance()

        remaining = num_questions
        chunk_index = 0

        try:
            while remaining > 0 and chunk_index < len(chunks):
                chunk = chunks[chunk_index]
                chunk_index += 1

                batch_size = min(MAX_Q_PER_CHUNK, remaining)

                prompt = build_prompt(chunk, batch_size, question_type, difficulty)

                output = await client.generate_async(prompt, max_tokens)

                quiz = None

                if output and output.strip():
                    output = output.strip().replace("```json", "").replace("```", "")
                    try:
                        quiz = parse_quiz_output(output, batch_size, question_type)
                    except Exception as e:
                        logger.error(f"Quiz parsing failed: {e}")

                        data = safe_json_load(output)
                        if data and "questions" in data:
                            quiz = data
                else:
                    logger.warning("Empty LLM output")
                if not quiz:
                    logger.warning(f"Chunk {chunk_index} se questions nahi mile, skip kar raha hoon")
                    continue

                for q in quiz["questions"]:
                    q_val = q.get("question", "")

                    if isinstance(q_val, dict):
                        q_val = q_val.get("text", "")
                    elif isinstance(q_val, list):
                        q_val = " ".join(map(str, q_val))

                    text = str(q_val).strip().lower()

                    if text not in used:
                        q["id"] = len(questions) + 1
                        questions.append(q)
                        used.add(text)
                        remaining -= 1
                        yield f"data: {json.dumps({'type': 'question', 'data': q})}\n\n"
                if remaining <= 0:
                    break
            data = {
                'type': 'done',
                'quiz': {'questions': questions[:num_questions]},
                'complete': len(questions) >= num_questions
            }

            yield f"data: {json.dumps(data)}\n\n"

        except Exception as e:
            data = {
                'type': 'done',
                'quiz': {'questions': questions},
                'error': str(e),
                'complete': False
            }
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)