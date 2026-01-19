from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests


class AnthropicClient:
    """Minimal Anthropic Messages API client (no SDK dependency)."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")

    def messages_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic error {r.status_code}: {r.text}")
        return r.json()

    @staticmethod
    def extract_text(resp: Dict[str, Any]) -> str:
        # content is a list of blocks; for text blocks, block['text']
        out = []
        for block in resp.get("content", []) or []:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                out.append(block["text"])
        return "\n".join(out).strip()
