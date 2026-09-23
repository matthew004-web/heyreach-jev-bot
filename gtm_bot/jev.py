"""Minimal TypeSafe System One (Jev) client over raw HTTP.

Raw HTTP instead of typesafe-sdk because the repo venv is Python 3.9.
Tracks tokens, requests, latency and cost so reports can show them.
"""

import os
import threading
import time

import requests

API_URL = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_MTOK = 0.042  # USD per million input tokens (jev-1.13); output tokens free
RETRY_STATUSES = {429, 500, 502, 503, 529}


class JevError(RuntimeError):
    pass


class Jev:
    def __init__(self, model="jev-latest", api_key=None, timeout=60, retries=4):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY is not set")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self._local = threading.local()
        self._lock = threading.Lock()
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "latencies": []}
        self.models_seen = set()

    def _session(self):
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })
            self._local.session = s
        return self._local.session

    def ask(self, state, questions):
        """Evaluate `questions` (raw API dicts) against `state`. Returns the answers map."""
        body = {"model": self.model, "state": state, "questions": questions}
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                r = self._session().post(API_URL, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise JevError(f"connection failed: {e}") from e
            if r.status_code in RETRY_STATUSES and attempt < self.retries:
                time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
                continue
            if r.status_code != 200:
                raise JevError(f"HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            with self._lock:
                self.usage["requests"] += 1
                self.usage["input_tokens"] += data["usage"]["input_tokens"]
                self.usage["output_tokens"] += data["usage"]["output_tokens"]
                self.usage["latencies"].append(time.time() - t0)
                self.models_seen.add(data.get("model"))
            return data["answers"]
        raise JevError("retries exhausted")

    def summary(self):
        lat = sorted(self.usage["latencies"]) or [0.0]
        return {
            "model": ", ".join(sorted(m for m in self.models_seen if m)) or self.model,
            "requests": self.usage["requests"],
            "input_tokens": self.usage["input_tokens"],
            "cost_usd": self.usage["input_tokens"] * PRICE_PER_MTOK / 1_000_000,
            "p50_latency_s": lat[len(lat) // 2],
            "p95_latency_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
        }
