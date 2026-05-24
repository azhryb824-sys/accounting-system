import json
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inference import MODEL_NAME, MODEL_OWNER, ask, extract_invoice_data


app = FastAPI(
    title=MODEL_NAME,
    description=f"واجهة خاصة لتشغيل نموذج الذكاء الاصطناعي المحاسبي الخاص بـ {MODEL_OWNER}.",
    version="1.1.0",
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


@app.get("/")
def home() -> dict[str, str]:
    return {
        "message": f"{MODEL_NAME} يعمل الآن كنموذج خاص.",
        "owner": MODEL_OWNER,
        "ask_endpoint": "/ask",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ready", "model": MODEL_NAME}


@app.post("/ask", response_model=AnswerResponse)
def ask_question(request: QuestionRequest) -> AnswerResponse:
    try:
        if request.image_base64:
            data = extract_invoice_data(
                question=request.question,
                image_base64=request.image_base64,
                media_type=request.media_type,
            )
            return AnswerResponse(
                model=MODEL_NAME,
                owner=MODEL_OWNER,
                answer=json.dumps(data, ensure_ascii=False),
                data=data,
            )

        answer = ask(request.question, max_new_tokens=request.max_new_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AnswerResponse(model=MODEL_NAME, owner=MODEL_OWNER, answer=answer)
