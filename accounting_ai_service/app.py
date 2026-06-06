import json
import os
import io
import re
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
import numpy as np
from pydantic import BaseModel, Field

from inference import MODEL_NAME, MODEL_OWNER, ask, extract_invoice_data, runtime_status


PRIVATE_ACCOUNTING_AI_API_KEY = os.environ.get("PRIVATE_ACCOUNTING_AI_API_KEY", "").strip()


app = FastAPI(
    title="جميل",
    description=f"واجهة جميل المستقلة للذكاء الاصطناعي، مقدمة من {MODEL_OWNER}.",
    version="2.0.0",
)


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="السؤال المطلوب إجابته.")
    max_new_tokens: int = Field(420, ge=20, le=1800, description="الحد الأعلى لطول الإجابة.")
    image_base64: str | None = Field(None, description="صورة أو ملف فاتورة مشفر Base64.")
    media_type: str | None = Field(None, description="نوع الملف المرفق مثل image/jpeg أو application/pdf.")


class AnswerResponse(BaseModel):
    model: str
    owner: str
    answer: str
    data: dict[str, Any] | None = None
    references: list[dict[str, str]] = []


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
    return {"status": "ready", **runtime_status()}


@app.post("/tts")
def synthesize_speech(request: SpeechRequest, x_accounting_ai_key: str | None = Header(default=None)) -> Response:
    if PRIVATE_ACCOUNTING_AI_API_KEY and x_accounting_ai_key != PRIVATE_ACCOUNTING_AI_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid accounting AI key.")
    try:
        audio = _arabic_tts().generate(request.text.strip(), speed=request.speed)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Arabic voice is unavailable: {exc}") from exc
    return Response(_wav_bytes(audio.samples, audio.sample_rate), media_type="audio/wav")


@app.post("/ask", response_model=AnswerResponse)
def ask_question(request: QuestionRequest, x_accounting_ai_key: str | None = Header(default=None)) -> AnswerResponse:
    if PRIVATE_ACCOUNTING_AI_API_KEY and x_accounting_ai_key != PRIVATE_ACCOUNTING_AI_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid accounting AI key.")
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

        answer = ask(request.question, max_new_tokens=request.max_new_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="تعذر تشغيل محرك الإجابة الآن. حاول مرة أخرى بعد قليل.",
        ) from exc

    answer, references = _separate_references(answer)
    return AnswerResponse(model="جميل", owner=MODEL_OWNER, answer=answer, references=references)
