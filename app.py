# Hugging Face Space (Gradio + ZeroGPU). Моделите се ONNX и работат на CPU.
# Една GPU-функција мора да постои за бесплатниот ZeroGPU, ама чатот не ја вика.
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import gradio as gr

try:
    import spaces
except ImportError:
    class spaces:  # локално, без пакетот на Space
        @staticmethod
        def GPU(fn):
            return fn

from app.core.budget import BUDGET_MSG, LlmBudgetExceeded
from app.core.generator import generate
from app.core.pipeline import EmptyQuestion, NeedGenerate, Ready, commit, plan, start_turn
from app.core.retriever import RetrievalUnavailable


@spaces.GPU
def _gpu_mesto() -> None:
    """ZeroGPU бара барем една ваква функција. Чатот не ја користи."""
    return None


def _izvori(izvori: list[dict]) -> str:
    redovi = []
    for izvor in izvori:
        naslov = izvor.get("title") or izvor.get("source") or "?"
        clen = izvor.get("article_no")
        if clen:
            naslov = f"{naslov} ({clen})"
        url = izvor.get("url")
        redovi.append(f"- {naslov}" + (f"\n  {url}" if url else ""))
    if not redovi:
        return ""
    return "\n\nИзвори:\n" + "\n".join(redovi)


def odgovori(prasanje: str, istorija: list, session_id: str | None):
    if not (prasanje or "").strip():
        return istorija, "", session_id
    try:
        turn = start_turn(prasanje, session_id)
        planiran = plan(turn)
        if isinstance(planiran, Ready):
            gotov = commit(turn, planiran.answer, planiran.sources, cacheable=planiran.cacheable)
        elif isinstance(planiran, NeedGenerate):
            tekst = generate(turn.prashanje, planiran.parchinja, turn.istorija)
            gotov = commit(turn, tekst, planiran.sources, cacheable=True)
        else:
            raise RuntimeError("непознат план")
        odgovor = gotov.answer + _izvori(gotov.sources)
        sid = turn.session_id
    except EmptyQuestion:
        odgovor, sid = "Напиши прашање.", session_id
    except LlmBudgetExceeded:
        odgovor, sid = BUDGET_MSG, session_id
    except RetrievalUnavailable:
        odgovor, sid = "Пребарувањето е недостапно. Обиди се повторно за минута.", session_id
    except Exception:
        odgovor, sid = "Настана грешка. Ако Space-от штотуку се разбуди, почекај минута и прати пак.", session_id

    istorija = list(istorija or [])
    istorija.append({"role": "user", "content": prasanje})
    istorija.append({"role": "assistant", "content": odgovor})
    return istorija, "", sid


with gr.Blocks(title="AskUGD") as demo:
    gr.Markdown(
        "## AskUGD\n"
        "Прашања за УГД, од официјалните документи. "
        "По будење првото прашање трае неколку минути, додека се вчитаат моделите."
    )
    sesija = gr.State(None)
    chat = gr.Chatbot(height=480)
    prasanje = gr.Textbox(label="Прашање", placeholder="На пример: колку чини втор циклус?")
    prasanje.submit(odgovori, [prasanje, chat, sesija], [chat, prasanje, sesija])

if __name__ == "__main__":
    demo.launch()
