# Prost klient za vlecenje dokumenti od uni API.
# Ocekuvani endpointi (prilagodi pateki ako bazata e drugacka):
#   GET {base}/api/v1/documents?updated_since=ISO
#   GET {base}/api/v1/documents/{id}/file
#   GET {base}/api/v1/documents/deleted?since=ISO
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DocumentInfo:
    id: str
    title: str
    updated_at: str | None
    content_hash: str | None
    download_url: str | None
    mime_type: str | None = None
    status: str | None = None


class DocApiError(RuntimeError):
    pass


class DocApiClient:
    """HTTP klient — samo gi zema podatocite, ne pišuwa vo Qdrant."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.doc_api_url or "").rstrip("/") + "/"
        self.token = token if token is not None else (settings.doc_api_token or "")
        self.timeout = timeout if timeout is not None else settings.doc_api_timeout
        if not self.base_url.strip("/"):
            raise DocApiError(
                "DOC_API_URL ne e postaven. Stavi go vo .env (npr. https://api.ugd.edu.mk)"
            )
        self._sesija = requests.Session()
        self._sesija.headers["Accept"] = "application/json"
        self._sesija.headers["User-Agent"] = "AskUGD-doc-pull/1.0"
        if self.token:
            self._sesija.headers["Authorization"] = f"Bearer {self.token}"

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._url(path)
        try:
            r = self._sesija.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise DocApiError(f"Mreza/API greska za {url}: {e}") from e
        if r.status_code >= 400:
            raise DocApiError(f"{url} → HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise DocApiError(f"{url} ne vrati JSON") from e

    def list_documents(self, updated_since: str | None = None) -> list[DocumentInfo]:
        """Lista na dokumenti. updated_since = ISO8601 ili None za site."""
        params: dict[str, Any] = {}
        if updated_since:
            params["updated_since"] = updated_since
        data = self._get_json("api/v1/documents", params=params or None)
        items = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise DocApiError("Ocekuvav lista 'items' vo odgovorot")
        out: list[DocumentInfo] = []
        for row in items:
            if not isinstance(row, dict) or not row.get("id"):
                logger.warning("Preskoknat nevaliden zapis: %r", row)
                continue
            out.append(
                DocumentInfo(
                    id=str(row["id"]),
                    title=str(row.get("title") or row["id"]),
                    updated_at=row.get("updated_at"),
                    content_hash=row.get("content_hash"),
                    download_url=row.get("download_url"),
                    mime_type=row.get("mime_type"),
                    status=row.get("status"),
                )
            )
        return out

    def download_file(self, doc: DocumentInfo) -> bytes:
        """PDF bajti za eden dokument."""
        if doc.download_url:
            path_or_url = doc.download_url
            url = path_or_url if path_or_url.startswith("http") else self._url(path_or_url)
        else:
            url = self._url(f"api/v1/documents/{doc.id}/file")
        try:
            r = self._sesija.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise DocApiError(f"Download greska za {url}: {e}") from e
        if r.status_code >= 400:
            raise DocApiError(f"{url} → HTTP {r.status_code}")
        if not r.content:
            raise DocApiError(f"{url} vrati prazen fajl")
        return r.content

    def list_deleted(self, since: str | None = None) -> list[str]:
        """ID-a na izbrisani dokumenti od 'since'."""
        params: dict[str, Any] = {}
        if since:
            params["since"] = since
        data = self._get_json("api/v1/documents/deleted", params=params or None)
        if isinstance(data, dict):
            ids = data.get("ids", [])
        else:
            ids = data
        if not isinstance(ids, list):
            raise DocApiError("Ocekuvav lista 'ids' vo deleted odgovorot")
        return [str(i) for i in ids]
