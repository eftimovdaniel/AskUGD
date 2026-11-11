FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    FASTEMBED_CACHE_PATH=/models/fastembed

WORKDIR /srv
COPY requirements-api.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -m appuser \
    && mkdir -p /models/fastembed \
    && chown -R appuser /models
USER appuser
# lazy_load gi simnuva fajlovite bez da gi drzi vo RAM. Inaku sekoj restart na free host gi vlece pak (3.2 GB).
RUN python -c "from fastembed import TextEmbedding, SparseTextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding(model_name='intfloat/multilingual-e5-large', lazy_load=True); SparseTextEmbedding(model_name='Qdrant/bm25', lazy_load=True); TextCrossEncoder(model_name='jinaai/jina-reranker-v2-base-multilingual', lazy_load=True)"
COPY --chown=appuser:appuser app ./app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
    CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)"
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} -b 0.0.0.0:${PORT:-8000} --timeout 120 --graceful-timeout 30"]
