# AskUGD — Backend (RAG)

AI асистент за Универзитет „Гоце Делчев“ – Штип. Одговара на прашања на
студенти врз официјални документи, на јазикот на кој е поставено прашањето.

**Стек:** PyMuPDF → FastEmbed (dense e5 + BM25 sparse) → Qdrant (hybrid) → cross-encoder rerank → LLM (OpenAI-компатибилен: GPT-4o-mini prod / Groq dev) → FastAPI

**Retrieval pipeline:** query translation → **hybrid search (dense + BM25, RRF fusion)** → score threshold → cross-encoder rerank → bounded loop (max_iterations).

**Продукциски можности:** rate limiting, опц. API key, заклучен CORS (+ credentials safety), prompt-injection guard (во query И во документите), XML изолација на контекст, retries со backoff, readiness проби, JSON логирање со request-id, метрики, конверзациска историја, streaming (SSE), eval test set.

---

## Структура

```
backend/
├── app/
│   ├── main.py              # FastAPI, CORS, rate-limit, /health /ready /metrics
│   ├── config.py            # сите поставки од .env
│   ├── security.py          # rate limit, API key, sanitize, injection guard
│   ├── observability.py     # JSON logging, request-id, метрики
│   ├── api/chat.py          # POST /chat (RAG + историја + грешки)
│   ├── core/
│   │   ├── vectorstore.py   # Qdrant hybrid (dense+BM25), retries, readiness
│   │   ├── retriever.py     # translate → hybrid → threshold → rerank → loop guard
│   │   ├── rerank.py        # cross-encoder (multilingual), со fallback
│   │   ├── translate.py     # query translation (cross-lingual)
│   │   ├── generator.py     # LLM (OpenAI-компат.), XML изолација, retries, streaming
│   │   └── history.py       # конверзациска историја по сесија (TTL)
│   └── models/schemas.py    # Pydantic модели
├── ingestion/
│   ├── pdf_loader.py        # PyMuPDF + чистење шум
│   ├── html_scraper.py      # BeautifulSoup за сесиски инфо
│   ├── chunker.py           # semantic chunk + overlap + injection neutralize
│   └── run_ingestion.py     # орбкестрација (+ богата метадата)
├── eval/
│   ├── test_questions.yaml  # тест прашања + очекувани извори
│   └── run_eval.py          # мери retrieval hit rate (regression test)
└── data/
    ├── pdfs/                # стави ги правилниците тука
    ├── pdfs.yaml            # наслов/линк за секој PDF (опц.)
    └── sources.yaml         # HTML линкови за scraping
```

## Структура на базата (Qdrant payload)

Секое парче (point) во Qdrant има вектори + payload полиња. Ова се полињата
што треба да ги имаш — се полнат автоматски од ingestion:

| Поле | Тип | Опис |
|---|---|---|
| _(dense vector)_ | float[1024] | семантички вектор (multilingual-e5) |
| _(sparse vector)_ | BM25 | клучни зборови (за hybrid search) |
| `text` | string | самиот текст на парчето (се враќа како document) |
| `source` | string | име на фајл или URL (уникатен клуч за бришење) |
| `title` | string | читлив наслов (пр. „Правилник за ЕКТС") — за приказ |
| `url` | string \| null | линк до изворот (widget-от го покажува како референца) |
| `doc_type` | string | `pdf` или `web` |
| `lang` | string | јазик на документот (`mk`) |
| `article_no` | string \| null | „Член N" за правилници (прецизно цитирање) |
| `section` | string \| null | наслов на секција / „дел N" |
| `chunk_index` | int | реден број на парчето во документот |
| `strategy` | string | `article` или `paragraph` |
| `word_count` | int | број зборови (за дијагностика) |
| `ingested_at` | ISO datetime | кога е внесено (за refresh на web) |

`article_no`, `title` и `url` се златни за citiranje: widget-от може да покаже
„Извор: Правилник за ЕКТС, Член 12" со кликлив линк.

## Инсталација

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env         # внеси LLM_API_KEY (OpenAI или Groq — види .env.example)

docker compose up -d qdrant redis   # локален Qdrant :6333 + Redis :6379
```

## Полнење на базата (ingestion)

```bash
cd backend
python -m ingestion.run_ingestion            # сите PDF + web извори
python -m ingestion.run_ingestion --only pdf # само PDF-ови
python -m ingestion.run_ingestion --only web # само web (за периодичен refresh)
```

Првото пуштање презема FastEmbed модел (~1GB) — трае малку. Потоа е брзо.

## Стартување на API

```bash
cd backend
uvicorn app.main:app --reload                                  # dev

# prod (цел stack: API + Qdrant + Redis):
docker compose up -d --build

# prod без Docker — со 2+ workers ЗАДОЛЖИТЕЛНО постави REDIS_URL во .env:
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2
```

**Rate limiting:** 20 бар./мин по сесија + 300 бар./мин по IP. IP лимитот е
намерно висок — на кампус WiFi стотици студенти делат иста јавна IP.

**Eval (regression test за retrieval)** — пушти по секоја промена на
chunking/модели/threshold:

```bash
python -m eval.run_eval
```

Тест:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Колку поени ми требаат за да пријавам испит?"}'
```

Follow-up прашање (со историја) — испрати `session_id`:

```bash
-d '{"question":"А ако сум вонреден?","session_id":"abc123"}'
```

Одговара и на англиски автоматски. Swagger: http://localhost:8000/docs

### Endpoints

| Endpoint | Намена |
|---|---|
| `POST /chat` | RAG одговор (+ извори, session_id) |
| `POST /chat/stream` | streaming одговор (SSE: sources → token → done) |
| `GET /health` | liveness — дали процесот работи |
| `GET /ready` | readiness — дали Qdrant е достапен |
| `GET /metrics` | requests, errors, avg latency |

## Евалуација (regression test)

```bash
python -m eval.run_eval    # мери retrieval hit rate врз тест прашања
```

Пушти го по секоја промена на chunking/threshold/reranker за да провериш
дали точноста се подобри или влоши. Додај нови прашања во `eval/test_questions.yaml`.

## Продукциска сигурност

- **Rate limiting** (`RATE_LIMIT`, default 20/min по IP) против злоупотреба.
- **API key** (опц.) — постави `API_ACCESS_KEY`; тогаш се бара `X-API-Key` header.
- **CORS** — во продукција постави `CORS_ORIGINS=https://www.ugd.edu.mk` (не `*`).
- **Prompt-injection guard** — влезот се чисти и ограничува; системскиот prompt
  е зацврстен да не третира инструкции од корисник како наредби.
- **Тајни** — само во `.env` (во `.gitignore`), никогаш во код/логови.

## Формат на одговорите (Markdown)

Моделот е инструиран да враќа **структуриран Markdown**: задебелени наслови на
чекори (**Чекор N:**), нумерирани/вгнездени списоци (1. → a. → i.), задебелени
износи и шифри, и **табели** за платни разбивки по статус/сесија. Пример за
„Како се пријавува испит?" дава чекори + табела со износи (70/370/670 денари).

⚠️ **Widget-от МОРА да рендерира Markdown** — инаку одговорот изгледа како суров
текст. Види `frontend-render-example.html` (користи `marked` + `DOMPurify` за
безбедно рендерирање, со стил за табели/списоци и со streaming поддршка).

Долгите структурирани одговори се контролираат со `MAX_ANSWER_TOKENS` (default 1200).

## Поврзување со frontend

Widget-от прави `POST /chat` со `{"question": "...", "session_id": "..."}` и
добива `{"answer": "...", "sources": [...], "session_id": "..."}`. Чувај го
`session_id` во browser-от за follow-up прашања. Постави `CORS_ORIGINS` во `.env`.

## Периодичен web refresh (сесии, колоквиуми)

Информациите за сесии се менуваат по година. Пушти го `--only web`
периодично (пр. cron еднаш неделно). Стариот контент за секој URL се
брише автоматски пред да се внесе новиот, па нема застарени распореди.

## Преод кон Qdrant Cloud

Само во `.env`:
```
QDRANT_URL=https://xxxx.cloud.qdrant.io:6333
QDRANT_API_KEY=your-cloud-key
```
Кодот останува ист.

## Белешки за квалитет

- **Anti-hallucination:** моделот одговара само од контекстот; ако нема
  информација, упатува кон студентска служба.
- **Чункирање:** правилниците се сечат по „Член"; кратки процедурални
  документи се чуваат цели со overlap.
- **Retrieval pipeline:** повеќе кандидати (`CANDIDATE_K`) → score threshold
  (`SCORE_THRESHOLD`) → cross-encoder rerank → најдобри `TOP_K` во LLM.
- **Reranker fallback:** ако reranker моделот не се вчита, retrieval-от
  продолжува без rerank наместо да падне.
- **Метадата:** секое парче носи `source` и `article_no` за цитирање извор.

## Покриеност на best-practices

| Практика | Како е решено |
|---|---|
| Loop guard / max_iterations | `MAX_RETRIEVAL_ITERATIONS` (default 3), тестирано дека запира |
| Anti-hallucination | системски prompt: „ако нема во контекст → признај" |
| Semantic chunking + overlap | по „Член"/параграф, ~15% overlap |
| Метадата референци | `title`, `url`, `article_no` во payload + враќање во `sources` |
| Multilingual embeddings | `intfloat/multilingual-e5-large` |
| Query translation | `translate.py` — превод на прашање пред пребарување |
| Hybrid search (BM25) | dense + BM25 sparse, RRF fusion во Qdrant |
| Re-ranking | cross-encoder `jina-reranker-v2-multilingual`, top_k филтер |
| Prompt injection (query) | `security.sanitize_question` + детекција |
| Prompt injection (документи) | `chunker.neutralize_injections` + XML `<context>` изолација |
| Context isolation | контекстот е во `<context></context>`, prompt го третира како податок |
| Streaming | `POST /chat/stream` (SSE) — токен по токен |
| Latency | hybrid+rerank намалуваат токени; ниска температура; retries |

**Забелешка за prompt caching:** OpenAI кешира префикси автоматски (>1024 токени); Groq (за разлика од Anthropic) нема експлицитно
prompt caching. Најголема заштеда доаѓа од reranking (помалку токени во контекст) и
кратки системски prompt-ови. Ако подоцна се префрлиш на провајдер со caching,
системскиот prompt е стабилен па е кеш-погоден.

## Безбедносен преглед (извршен)

- ✅ Нема `eval/exec/os.system/subprocess/shell=True` во кодот.
- ✅ Нема хардкодирани тајни; `.env` е во `.gitignore`.
- ✅ CORS+credentials bug поправен — credentials се дозволени само со
  експлицитни origins (не со `*`).
- ✅ Injection одбрана во длабочина: sanitize на query + neutralize на документи
  + XML изолација на контекст.
- ✅ Rate limiting, опц. API key, input length caps, control-char stripping.
- ✅ HTTP scraper има timeout; нема следење на непроверени редиректи во LLM.
- ✅ Грешките враќаат генерички пораки (без стек трага кон клиент); деталите
  одат само во логови.

## Скалирање (кога ќе затреба)

- Историјата е in-memory (една инстанца). За повеќе replikи замени
  `history.py` со Redis (истиот интерфејс).
- Метриките се in-memory. За продукција приклучи Prometheus (`/metrics`).
- FastEmbed и reranker моделите се вчитуваат еднаш по процес — користи
  `-w 2` или повеќе gunicorn workers според RAM.
