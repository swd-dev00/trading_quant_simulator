import os

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="TradingQ")

_anthropic_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


SYSTEM_PROMPT = (
    "You are Astrid, an intelligent quantitative trading assistant integrated into the "
    "TradingQ simulation platform. You help users with strategy design, backtesting, "
    "risk management, portfolio optimization, and quantitative finance concepts. "
    "Be concise, precise, and grounded in financial theory. Always note that simulated "
    "results do not guarantee real-world performance."
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[Message] = []


@app.get("/")
def read_root():
    return {"status": "ok"}


@app.get("/healthz")
def health_check():
    return {"ok": True}


@app.post("/chat")
def chat(request: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in request.history]
    messages.append({"role": "user", "content": request.message})

    client = get_client()

    def generate():
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text

    return StreamingResponse(generate(), media_type="text/plain")
