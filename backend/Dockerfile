FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models
# HF_HOME: кеш за embedding моделите — монтирај volume за брз старт

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd -m appuser && mkdir -p /models && chown appuser /models
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

# WEB_CONCURRENCY: број workers. Секој worker вчитува свои embedding модели
# (~2GB RAM за e5-large) — димензионирај: 2 workers ≈ 4-5GB RAM.
# Со 2+ workers ЗАДОЛЖИТЕЛНО постави REDIS_URL.
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:8000 --timeout 120 --graceful-timeout 30"]
