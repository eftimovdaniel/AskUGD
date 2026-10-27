# startuvanje na modelot od kesot na uredot da ne mora da se zagreva modelot predolgo za da e polesno za strtuvanje i so toa ke se namele vremeto potrebno da se dobie 
# prviot odgovor od modelot do studentot

cd "$(dirname "$0")"

export HF_HOME="$HOME/.cache/askugd/hf"
export FASTEMBED_CACHE_PATH="$HOME/.cache/askugd/fastembed"
mkdir -p "$HF_HOME" "$FASTEMBED_CACHE_PATH"
echo "Кеш за модели: $HOME/.cache/askugd"
echo "Стартувам backend на http://localhost:8000 ..."
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
