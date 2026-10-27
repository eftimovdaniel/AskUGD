# AskUGD

A RAG-based assistant that answers students' questions about Goce Delčev University –
Štip, grounded strictly in official documents.

Large language models are fluent, but when they do not know something they tend to invent it. For a system that provides real prices, deadlines and procedure codes, that is not acceptable. 
AskUGD addresses this with Retrieval-Augmented Generation: it first searches the university's official documents, retrieves the most relevant passages, and
only then lets the model compose an answer based solely on them, with the source cited.

## Features

- Hybrid search — dense semantic embeddings (e5-large) combined with sparse keyword matching (BM25), fused via Reciprocal Rank Fusion (RRF).
- Re-ranking with a cross-encoder to order results by true relevance.
- Multilingual — replies in the language of the question (Macedonian in Cyrillic or Latin script, English, Turkish, and others).
- Verifiable answers — each response links back to the official source document.
- Table-aware extraction — prices and codes remain bound to their columns, including tables that span multiple pages.
- Defense in depth — five-layer prompt-injection protection, rate limiting, and signed session identifiers.
- Streaming responses and a cache for frequently asked questions.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Vector database | Qdrant |
| Embeddings / rerank | multilingual-e5-large, BM25, jina-reranker-v2 |
| LLM | Google Gemini and Claude API|
| Frontend | TypeScript web widget |
