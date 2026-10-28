#!/usr/bin/env sh
# Prod-like start: gunicorn + povekje workers.
# REDIS_URL mora da e postaven — inaku history/cache/rate-limit ne se delat.

cd "$(dirname "$0")"

if [ -z "${REDIS_URL:-}" ]; then
  if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a
    . ./.env
    set +a
  fi
fi

if [ -z "${REDIS_URL:-}" ]; then
  echo "REDIS_URL не е поставен." >&2
  echo "За 2+ workers стави REDIS_URL=redis://127.0.0.1:6379/0 во .env" >&2
  echo "(види .env.example). За единечен worker без Redis користи ./start.sh" >&2
  exit 1
fi

export HF_HOME="${HF_HOME:-$HOME/.cache/askugd/hf}"
export FASTEMBED_CACHE_PATH="${FASTEMBED_CACHE_PATH:-$HOME/.cache/askugd/fastembed}"
mkdir -p "$HF_HOME" "$FASTEMBED_CACHE_PATH"

WORKERS="${WEB_CONCURRENCY:-2}"
echo "Кеш за модели: $HOME/.cache/askugd"
echo "REDIS_URL=$REDIS_URL"
echo "Стартувам prod-like backend (gunicorn, $WORKERS workers) на http://localhost:8000 ..."
exec .venv/bin/gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w "$WORKERS" \
  -b 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30
