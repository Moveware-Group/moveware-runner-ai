import os
from typing import Dict

import requests


class OpenAIClient:
    """Minimal OpenAI Responses API wrapper.

    If you prefer, replace this with the official SDK.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.2-codex")

    def complete(self, prompt: str, max_output_tokens: int = 1200) -> Dict:
        if not self.api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")
        url = "https://api.openai.com/v1/responses"
        payload = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        r = requests.post(url, json=payload, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()
