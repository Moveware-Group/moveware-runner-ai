from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import requests


class OpenAIClient:
    """Minimal OpenAI Responses API client (no SDK dependency)."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def responses_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")
        return r.json()

    @staticmethod
    def extract_text(resp: Dict[str, Any]) -> str:
        # Responses API can return output_text in convenience field, or within output[].content[]
        if isinstance(resp.get("output_text"), str):
            return resp["output_text"]
        out = []
        for item in resp.get("output", []) or []:
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                    out.append(c["text"])
        return "\n".join(out).strip()
