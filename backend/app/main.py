from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from app.core.generator import generate_answer
from app.core.query_translation import translate_query
from app.core.retriever import retrieve

app = FastAPI(title="AskUGD")

class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    answer: str

@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()

    # 1. Dokolku prasanjeto e postaveno na makedonski treba da go najpravo prevedeme na angliski 
    queries = [question]
    translation = translate_query(question)
    if translation.translated:
        queries.append(translation.translated)
    # 2.OD dokumentacijata se pronaogaat najrelevantnite parcinja, vektori, koj najmnogu odgovaaraat na postavenoto prasanje
    context_chunks = retrieve(queries)
    # 3. Generiranje na odgovor od LLM na jazikot na koj e postaveno prasanjeto
    answer = generate_answer(question, context_chunks)
    return AskResponse(answer=answer)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}