# Server-issued session_id: format + HMAC (koga ima SESSION_SECRET / API_ACCESS_KEY).
# Potpisot spreci izmisleni ID-a; ukraden ID od sessionStorage seuste raboti (nema login).
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
from app.config import settings

# Tesen charset i gornja granica: ID-to vleguva vo Redis kluc i vo log, pa ne smee
# da nosi razdelnici, novi redovi ili proizvolna dolzina od klientot.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_SIG_LEN = 16   # 64 bita od digest-ot; dovolno protiv pogodovanje, a ID-to ostanuva kratko

def _secret() -> bytes | None:
    """Bez postaven kluc vrakja None — togas ID-to e samo nonce, bez potpis."""
    raw = (settings.session_secret or settings.api_access_key or "").strip()
    return raw.encode() if raw else None

def mint_session_id() -> str:
    nonce = secrets.token_urlsafe(16)
    secret = _secret()
    if not secret:
        return nonce
    sig = hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]
    return f"{nonce}-{sig}"

def verify_session_id(session_id: str) -> bool:
    if not SESSION_ID_RE.fullmatch(session_id or ""):
        return False
    secret = _secret()
    if not secret:
        return True                      # razvojna sredina: proveri samo format
    if "-" not in session_id:
        return False
    # rsplit, ne split: token_urlsafe i samiot moze da sodrzi „-“, pa potpisot
    # se odzema od desno — inaku nonce-ot bi se skratil i proverkata sekogas bi padnala.
    nonce, sig = session_id.rsplit("-", 1)
    if len(sig) != _SIG_LEN:
        return False
    expected = hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]
    return hmac.compare_digest(sig, expected)   # konstantno vreme, kako kaj API klucot

def resolve_session_id(provided: str | None) -> str:
    """Falsifikuvan ili istecen ID ne e greska — tivko se izdava nov, vidzetot prodolzuva."""
    if provided and verify_session_id(provided):
        return provided
    return mint_session_id()
