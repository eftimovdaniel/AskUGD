from __future__ import annotations
import re
from dataclasses import dataclass, field

ARTICLE_RE = re.compile(r"(?m)^\s*(Член\s+\d+[а-я]?)\b")
MAX_WORDS = 1000
OVERLAP_RATIO = 0.15          # ~15% преклопување меѓу парчиња
PARAGRAPH_TARGET = 800
MIN_CHUNK_WORDS = 8

# Фрази типични за prompt injection во текст (mk + en). Ги неутрализираме.
_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"forget\s+(all\s+)?(previous|prior)\s+instructions?|"
    r"you\s+are\s+now\b|act\s+as\s+(a|an)\b|pretend\s+to\s+be\b|"
    r"new\s+instructions?\s*:|system\s*prompt|developer\s+message|"
    r"do\s+not\s+follow\s+the\s+system|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|нови\s+инструкции\s*:|"
    r"системски\s+промпт|однесувај\s+се\s+како)"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)

def neutralize_injections(text: str) -> str:
    return _INJECTION_RE.sub("[отстранета инструкција]", text)

def _split_by_words(text: str, max_words: int = MAX_WORDS) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    overlap = max(0, int(max_words * OVERLAP_RATIO))
    step = max(1, max_words - overlap)
    out, i = [], 0
    while i < len(words):
        out.append(" ".join(words[i:i + max_words]))
        if i + max_words >= len(words):
            break
        i += step
    return out

def _chunk_by_articles(text: str) -> list[Chunk]:
    matches = list(ARTICLE_RE.finditer(text))
    chunks: list[Chunk] = []
    if matches and matches[0].start() > 0:
        intro = text[:matches[0].start()].strip()
        if len(intro.split()) > 20:
            for j, piece in enumerate(_split_by_words(intro)):
                chunks.append(Chunk(piece, {"article_no": None, "section": "вовед", "part": j}))
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        label = m.group(1).strip()
        for j, piece in enumerate(_split_by_words(body)):
            chunks.append(Chunk(piece, {"article_no": label, "part": j}))
    return chunks

def _chunk_by_paragraphs(text: str) -> list[Chunk]:
    raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    paras: list[str] = []
    for p in raw_paras:
        paras.extend(_split_by_words(p))    # осигурај дека ниту еден пасус не е џин
    chunks: list[Chunk] = []
    buff: list[str] = []
    count, idx = 0, 0
    for p in paras:
        w = len(p.split())
        if count + w > PARAGRAPH_TARGET and buff:
            chunks.append(Chunk("\n\n".join(buff), {"section": f"дел {idx}"}))
            idx += 1
            # overlap: задржи го последниот пасус само ако е разумно мал
            last = buff[-1]
            if len(last.split()) <= PARAGRAPH_TARGET // 2:
                buff = [last]
                count = len(last.split())
            else:
                buff, count = [], 0
        buff.append(p)
        count += w
    if buff:
        chunks.append(Chunk("\n\n".join(buff), {"section": f"дел {idx}"}))
    return chunks


def chunk_document( text: str, source: str, doc_type: str = "pdf", title: str | None = None, url: str | None = None, lang: str = "mk",) -> list[Chunk]:
    if not text or not text.strip():
        return []
    text = _CONTROL_RE.sub("", text)
    has_articles = len(ARTICLE_RE.findall(text)) >= 3
    chunks = _chunk_by_articles(text) if has_articles else _chunk_by_paragraphs(text)
    result: list[Chunk] = []
    for c in chunks:
        if len(c.text.split()) < MIN_CHUNK_WORDS:
            continue
        c.text = neutralize_injections(c.text)   # безбедност при ingestion
        c.metadata.update({
            "source": source,
            "title": title or source,
            "url": url,
            "doc_type": doc_type,
            "lang": lang,
            "chunk_index": len(result),          # индекс по филтрирање — без дупки
            "strategy": "article" if has_articles else "paragraph",
            "word_count": len(c.text.split()),
        })
        result.append(c)
    return result
