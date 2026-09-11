"""Thin WaniKani API v2 client."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx

BASE_URL = "https://api.wanikani.com/v2/"
REVISION = "20170710"


class ApiError(RuntimeError):
    pass


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class WaniKani:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Wanikani-Revision": REVISION,
                "User-Agent": "wanikani-tui/0.1",
            },
            timeout=timeout,
        )
        self._raw = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self._client.close()
        self._raw.close()

    # -- low level -----------------------------------------------------------

    def _request(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        for attempt in range(5):
            resp = self._client.request(method, url, **kw)
            if resp.status_code == 429:
                reset = resp.headers.get("RateLimit-Reset")
                wait = 5.0
                if reset:
                    try:
                        wait = max(1.0, float(reset) - time.time() + 0.5)
                    except ValueError:
                        pass
                time.sleep(min(wait, 60))
                continue
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("error", resp.text)
                except Exception:
                    detail = resp.text
                raise ApiError(f"{method} {url} -> {resp.status_code}: {detail}")
            return resp.json()
        raise ApiError(f"{method} {url}: rate limited too many times")

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            if isinstance(v, (list, tuple, set)):
                v = ",".join(str(x) for x in v)
            elif isinstance(v, bool):
                v = "true" if v else "false"
            clean[k] = v
        return self._request("GET", path, params=clean)

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        page = self.get(path, params)
        while True:
            yield from page.get("data", [])
            next_url = (page.get("pages") or {}).get("next_url")
            if not next_url:
                return
            page = self._request("GET", next_url)

    # -- resources -----------------------------------------------------------

    def user(self) -> dict[str, Any]:
        return self.get("user")["data"]

    def summary(self) -> dict[str, Any]:
        return self.get("summary")["data"]

    def subjects(self, updated_after: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate("subjects", {"updated_after": updated_after})

    def assignments(self, updated_after: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate("assignments", {"updated_after": updated_after})

    def study_materials(self, updated_after: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate("study_materials", {"updated_after": updated_after})

    def review_statistics(self, updated_after: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate("review_statistics", {"updated_after": updated_after})

    def create_review(self, assignment_id: int, incorrect_meaning: int, incorrect_reading: int) -> dict[str, Any]:
        body = {
            "review": {
                "assignment_id": assignment_id,
                "incorrect_meaning_answers": incorrect_meaning,
                "incorrect_reading_answers": incorrect_reading,
            }
        }
        return self._request("POST", "reviews", json=body)

    def start_assignment(self, assignment_id: int) -> dict[str, Any]:
        return self._request("PUT", f"assignments/{assignment_id}/start", json={"assignment": {}})

    def fetch_bytes(self, url: str) -> bytes:
        resp = self._raw.get(url)
        resp.raise_for_status()
        return resp.content
