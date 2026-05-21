from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inference import MODEL_NAME, MODEL_OWNER, ask, get_model


app = FastAPI(
    title=MODEL_NAME,
    description=f"واجهة محلية خاصة لتشغيل نموذج الذكاء الاصطناعي المحاسبي الخاص بـ {MODEL_OWNER}.",
    version="1.0.0",
)


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="السؤال المطلوب إجابته.")
    max_new_tokens: int = Field(120, ge=20, le=300, description="الحد الأعلى لطول الإجابة.")


class AnswerResponse(BaseModel):
    model: str
    owner: str
    answer: str


@app.on_event("startup")
def warm_up_model() -> None:
    get_model()


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
        answer = ask(request.question, max_new_tokens=request.max_new_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AnswerResponse(model=MODEL_NAME, owner=MODEL_OWNER, answer=answer)
