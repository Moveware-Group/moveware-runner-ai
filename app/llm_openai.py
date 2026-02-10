from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, TypeVar, Callable

import requests


T = TypeVar('T')


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
) -> T:
    """Retry function with exponential backoff for rate limits."""
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
                "503" in error_msg or
                "timeout" in error_msg
            )
            
            if should_retry and attempt < max_retries - 1:
                print(f"Rate limited (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                time.sleep(delay)
                delay *= backoff_factor
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
        """Convenience method to create a response and extract text.
        
        Supports both standard Chat Completions API and Responses API.
        """
        # Try Responses API format first (based on base_url/responses endpoint)
        if "/responses" in self.base_url or "responses" in self.base_url.lower():
            # Responses API uses 'input' parameter with combined prompt
            # Only send parameters the Responses API actually supports
            combined_input = f"{system}\n\n{user}"
            payload = {
                "model": model,
                "input": combined_input,
            }
            
            try:
                resp = self.responses_create(payload)
                return self.extract_text(resp)
            except Exception as e:
                # If Responses API fails, fall through to try Chat Completions
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
            # Standard OpenAI response format
            if "choices" in resp and len(resp["choices"]) > 0:
                return resp["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        
        # Final fallback: try responses endpoint with 'input' parameter (minimal params)
        combined_input = f"{system}\n\n{user}"
        payload = {
            "model": model,
            "input": combined_input,
        }
        resp = self.responses_create(payload)
        return self.extract_text(resp)
