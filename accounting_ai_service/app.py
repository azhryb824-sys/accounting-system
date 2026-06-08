import json
import logging
import os
import io
import re
import wave
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
import numpy as np
from pydantic import BaseModel, Field

from inference import (
    MODEL_NAME,
    MODEL_OWNER,
    _open_web_search_answer,
    ask,
    extract_invoice_data,
    runtime_status,
)
from intelligence import assess_answer, plan_query, resolve_followup
from knowledge_store import initialize as initialize_knowledge, status as knowledge_status
from knowledge_updater import update as update_knowledge


LOGGER = logging.getLogger("jameel")
JAMEEL_API_KEY = (
    os.environ.get("JAMEEL_API_KEY")
    or os.environ.get("PRIVATE_ACCOUNTING_AI_API_KEY", "")
).strip()
KNOWLEDGE_UPDATE_INTERVAL_HOURS = max(
    0, int(os.environ.get("JAMEEL_KNOWLEDGE_UPDATE_INTERVAL_HOURS", "24") or 0)
)


app = FastAPI(
    title="جميل",
    description=f"واجهة جميل المستقلة للذكاء الاصطناعي، مقدمة من {MODEL_OWNER}.",
    version="2.0.0",
)


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="السؤال المطلوب إجابته.")
    max_new_tokens: int = Field(420, ge=20, le=1800, description="الحد الأعلى لطول الإجابة.")
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="آخر رسائل المحادثة للحفاظ على سياق الأسئلة المتتابعة.",
    )
    image_base64: str | None = Field(None, description="صورة أو ملف فاتورة مشفر Base64.")
    media_type: str | None = Field(None, description="نوع الملف المرفق مثل image/jpeg أو application/pdf.")


class AnswerResponse(BaseModel):
    model: str
    owner: str
    answer: str
    data: dict[str, Any] | None = None
    references: list[dict[str, str]] = Field(default_factory=list)
    used_web: bool = False
    elapsed_ms: int = 0
    response_variant: int = 0
    intelligence: dict[str, Any] = Field(default_factory=dict)


def _normalized_question(value: str) -> str:
    value = re.sub(r"[^\w\s]+", " ", value.lower())
    value = value.replace("ماهي", "ما هي").replace("ماهو", "ما هو")
    return re.sub(r"\s+", " ", value).strip()


def _response_variant(question: str, history: list[dict[str, str]]) -> int:
    target = _normalized_question(question)
    if not target:
        return 0
    repeats = sum(
        1
        for item in history
        if str(item.get("role", "")).lower() == "user"
        and _normalized_question(str(item.get("content", ""))) == target
    )
    return repeats % 4


def _vary_answer_style(answer: str, variant: int) -> str:
    if not answer or variant == 0:
        return answer
    substitutions = (
        (("هي", "تعني"), ("مثل", "ومن أمثلتها"), ("عادة", "في الغالب")),
        (("هي", "يمكن تعريفها بأنها"), ("يساعد", "يسهم"), ("تشمل", "تتضمن")),
        (("يعني", "يقصد به"), ("يجب", "من الضروري"), ("مثل", "على سبيل المثال")),
    )
    varied = answer
    for source, replacement in substitutions[(variant - 1) % len(substitutions)]:
        varied = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", replacement, varied, count=1)

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!؟])\s+", varied)
        if part.strip()
    ]
    if variant >= 2 and len(sentences) > 1:
        sentences = sentences[1:] + sentences[:1]
        varied = " ".join(sentences)

    introductions = (
        "بصياغة أخرى:",
        "من زاوية أوضح:",
        "يمكن تلخيص الفكرة هكذا:",
    )
    return f"{introductions[(variant - 1) % len(introductions)]}\n{varied}"


def _question_with_history(question: str, history: list[dict[str, str]]) -> str:
    clean_history = []
    for item in history[-8:]:
        role = str(item.get("role", "")).strip().lower()
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()[:1200]
        if role in {"user", "assistant"} and content:
            clean_history.append((role, content))
    if not clean_history:
        return question
    lines = ["سياق المحادثة السابقة:"]
    for role, content in clean_history:
        label = "المستخدم" if role == "user" else "جميل"
        lines.append(f"{label}: {content}")
    lines.extend(["", f"سؤال المستخدم: {question}"])
    return "\n".join(lines)


def _separate_references(answer: str) -> tuple[str, list[dict[str, str]]]:
    marker = "\nروابط التحقق:"
    if marker not in answer:
        return answer.strip(), []
    clean_answer, raw_references = answer.split(marker, 1)
    references = []
    for line in raw_references.splitlines():
        match = re.match(r"^\s*-\s*(.*?):\s*(https?://\S+)\s*$", line)
        if match:
            references.append({"title": match.group(1).strip(), "url": match.group(2).strip()})
    return clean_answer.strip(), references


def _require_api_key(api_key):
    if JAMEEL_API_KEY and api_key != JAMEEL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Jameel API key.")


def _knowledge_update_loop():
    while KNOWLEDGE_UPDATE_INTERVAL_HOURS:
        try:
            update_knowledge()
        except Exception:
            pass
        time.sleep(KNOWLEDGE_UPDATE_INTERVAL_HOURS * 3600)


@app.on_event("startup")
def start_independent_services():
    initialize_knowledge()
    if KNOWLEDGE_UPDATE_INTERVAL_HOURS:
        threading.Thread(target=_knowledge_update_loop, daemon=True).start()


class SpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    speed: float = Field(1.0, ge=0.75, le=1.25)


@lru_cache(maxsize=1)
def _arabic_tts():
    import sherpa_onnx
    voice_dir = Path(__file__).resolve().parent / "models" / "voices" / "vits-piper-ar_JO-kareem-medium"
    vits = sherpa_onnx.OfflineTtsVitsModelConfig(
        model=str(voice_dir / "ar_JO-kareem-medium.onnx"),
        tokens=str(voice_dir / "tokens.txt"),
        data_dir=str(voice_dir / "espeak-ng-data"),
    )
    model_config = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2, provider="cpu")
    return sherpa_onnx.OfflineTts(
        sherpa_onnx.OfflineTtsConfig(model=model_config, max_num_sentences=2)
    )


def _wav_bytes(samples, sample_rate):
    pcm = np.clip(np.asarray(samples) * 32767, -32768, 32767).astype(np.int16)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


@app.get("/", response_class=HTMLResponse)
@app.get("/jameel", response_class=HTMLResponse)
def jameel_interface() -> HTMLResponse:
    interface_path = Path(__file__).resolve().parent / "templates" / "jameel.html"
    return HTMLResponse(interface_path.read_text(encoding="utf-8"))


@app.get("/api-info")
def api_info() -> dict[str, str]:
    status = runtime_status()
    return {
        "message": "جميل يعمل الآن كمساعد ذكاء اصطناعي مستقل.",
        "owner": MODEL_OWNER,
        "backend": str(status.get("backend", "")),
        "ollama_model": str(status.get("ollama_model", "")),
        "ask_endpoint": "/ask",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ready", "knowledge": knowledge_status(), **runtime_status()}


@app.post("/tts")
def synthesize_speech(request: SpeechRequest, x_accounting_ai_key: str | None = Header(default=None)) -> Response:
    _require_api_key(x_accounting_ai_key)
    try:
        audio = _arabic_tts().generate(request.text.strip(), speed=request.speed)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Arabic voice is unavailable: {exc}") from exc
    return Response(_wav_bytes(audio.samples, audio.sample_rate), media_type="audio/wav")


@app.post("/ask", response_model=AnswerResponse)
def ask_question(request: QuestionRequest, x_accounting_ai_key: str | None = Header(default=None)) -> AnswerResponse:
    _require_api_key(x_accounting_ai_key)
    started_at = time.perf_counter()
    try:
        if request.image_base64:
            data = extract_invoice_data(
                question=request.question,
                image_base64=request.image_base64,
                media_type=request.media_type,
            )
            return AnswerResponse(
                model="جميل",
                owner=MODEL_OWNER,
                answer=json.dumps(data, ensure_ascii=False),
                data=data,
            )

        resolved_question = resolve_followup(request.question, request.history)
        query_plan = plan_query(resolved_question)
        contextual_question = _question_with_history(resolved_question, request.history)
        try:
            answer = ask(contextual_question, max_new_tokens=request.max_new_tokens)
        except Exception:
            if not request.history:
                raise
            LOGGER.exception("Contextual answer failed; retrying without conversation history.")
            answer = ask(request.question, max_new_tokens=request.max_new_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Jameel answer endpoint failed.")
        raise HTTPException(
            status_code=503,
            detail="تعذر تشغيل محرك الإجابة الآن. حاول مرة أخرى بعد قليل.",
        ) from exc

    answer, references = _separate_references(answer)
    initial_quality = assess_answer(resolved_question, answer, references)
    if initial_quality["level"] == "low":
        recovered = _open_web_search_answer(resolved_question)
        if recovered:
            answer, references = _separate_references(recovered)
    variant = _response_variant(request.question, request.history)
    answer = _vary_answer_style(answer, variant)
    quality = assess_answer(resolved_question, answer, references)
    return AnswerResponse(
        model="جميل",
        owner=MODEL_OWNER,
        answer=answer,
        references=references,
        used_web=bool(references),
        elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        response_variant=variant,
        intelligence={"plan": query_plan.to_dict(), "quality": quality},
    )


@app.get("/knowledge/status")
def get_knowledge_status(x_accounting_ai_key: str | None = Header(default=None)):
    _require_api_key(x_accounting_ai_key)
    return {"ok": True, **knowledge_status()}


@app.post("/knowledge/update")
def run_knowledge_update(x_accounting_ai_key: str | None = Header(default=None)):
    _require_api_key(x_accounting_ai_key)
    return {"ok": True, "processed": update_knowledge(), **knowledge_status()}
