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
    
    def chat_completion(self, messages: list, max_tokens: int = 4000, temperature: float = 1.0) -> Dict:
        """Send a chat completion request to OpenAI API.
        
        Note: For gpt-5.2-codex, use complete() method with /v1/responses instead.
        This method is for standard chat models like gpt-4o, gpt-4-turbo, etc.
        """
        if not self.api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")
        
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=180)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"OpenAI model '{self.model}' not found at /v1/chat/completions.\n"
                    f"For gpt-5.2-codex, the system should use the complete() method instead.\n"
                    f"If using standard OpenAI models, valid options: gpt-4o, gpt-4-turbo, gpt-4, gpt-3.5-turbo"
                ) from e
            raise
