from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, TypeVar, Callable

import requests


T = TypeVar('T')


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 5,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.5,
    max_delay: float = 120.0
) -> T:
    """Retry function with exponential backoff for rate limits and transient errors."""
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            error_msg = str(e).lower()
            
            should_retry = (
                "rate" in error_msg or 
                "429" in error_msg or 
                "502" in error_msg or
                "503" in error_msg or
                "504" in error_msg or
                "timeout" in error_msg or
                "timed out" in error_msg or
                "connection" in error_msg or
                "overloaded" in error_msg
            )
            
            if should_retry and attempt < max_retries - 1:
                print(f"Transient error (attempt {attempt + 1}/{max_retries}): {str(e)[:150]}...")
                print(f"Retrying in {delay:.0f}s...")
                time.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
                continue
            
            raise
    
    raise last_exception or RuntimeError(f"Failed after {max_retries} retries")


class OpenAIClient:
    """Minimal OpenAI Responses API client (no SDK dependency)."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def chat_completions_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Standard OpenAI Chat Completions API with retry."""
        def _make_request():
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
            if r.status_code >= 400:
                raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")
            return r.json()
        
        return retry_with_backoff(_make_request, max_retries=3)

    def responses_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Legacy/custom responses endpoint with retry."""
        def _make_request():
            url = f"{self.base_url}/responses"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
            if r.status_code >= 400:
                raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")
            return r.json()
        
        return retry_with_backoff(_make_request, max_retries=3)

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

    def responses_text(self, model: str, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.2) -> str:
        """Convenience method to create a response and extract text."""
        text, _ = self.responses_text_with_usage(model, system, user, max_tokens, temperature)
        return text

    def responses_text_with_usage(
        self, model: str, system: str, user: str,
        max_tokens: int = 4000, temperature: float = 0.2
    ) -> tuple[str, dict]:
        """Create response and return (text, usage_dict with input_tokens, output_tokens)."""
        usage = {"input_tokens": 0, "output_tokens": 0}
        # Try Responses API format first
        if "/responses" in self.base_url or "responses" in self.base_url.lower():
            combined_input = f"{system}\n\n{user}"
            payload = {"model": model, "input": combined_input}
            try:
                resp = self.responses_create(payload)
                text = self.extract_text(resp)
                u = resp.get("usage") or {}
                usage["input_tokens"] = u.get("input_tokens") or u.get("prompt_tokens") or 0
                usage["output_tokens"] = u.get("output_tokens") or u.get("completion_tokens") or 0
                return text, usage
            except Exception:
                pass
        # Try standard Chat Completions API
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        try:
            resp = self.chat_completions_create(payload)
            if "choices" in resp and len(resp["choices"]) > 0:
                text = resp["choices"][0]["message"]["content"].strip()
                u = resp.get("usage") or {}
                usage["input_tokens"] = u.get("prompt_tokens", 0)
                usage["output_tokens"] = u.get("completion_tokens", 0)
                return text, usage
        except Exception:
            pass
        # Final fallback
        combined_input = f"{system}\n\n{user}"
        resp = self.responses_create({"model": model, "input": combined_input})
        text = self.extract_text(resp)
        u = resp.get("usage") or {}
        usage["input_tokens"] = u.get("input_tokens") or u.get("prompt_tokens") or 0
        usage["output_tokens"] = u.get("output_tokens") or u.get("completion_tokens") or 0
        return text, usage
