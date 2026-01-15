import os
from typing import Dict

import requests


class ClaudeClient:
    """Minimal Anthropic Messages API wrapper.

    If you prefer, replace this with the official SDK.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        if not self.api_key:
            raise RuntimeError("Missing ANTHROPIC_API_KEY")

    def generate_json(self, prompt: str) -> Dict:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        text = "".join(part.get("text", "") for part in data.get("content", []))
        import json

        return json.loads(text)
