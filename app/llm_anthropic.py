from __future__ import annotations

import json
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
    """
    Retry function with exponential backoff.
    
    Handles rate limits and transient errors gracefully.
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            error_msg = str(e).lower()
            
            # Only retry on rate limits or transient errors
            should_retry = (
                "rate" in error_msg or 
                "429" in error_msg or 
                "503" in error_msg or
                "timeout" in error_msg or
                "overloaded" in error_msg
            )
            
            if should_retry and attempt < max_retries - 1:
                print(f"Transient error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                time.sleep(delay)
                delay *= backoff_factor
                continue
            
            # Don't retry other errors
            raise
    
    raise last_exception or RuntimeError(f"Failed after {max_retries} retries")


class AnthropicClient:
    """Minimal Anthropic Messages API client (no SDK dependency)."""

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")

    def messages_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        def _make_request():
            url = f"{self.base_url}/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",  # Enable caching support
                "content-type": "application/json",
            }
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
            if r.status_code >= 400:
                raise RuntimeError(f"Anthropic error {r.status_code}: {r.text}")
            return r.json()
        
        return retry_with_backoff(_make_request, max_retries=3)

    @staticmethod
    def extract_text(resp: Dict[str, Any]) -> str:
        # content is a list of blocks; for text blocks, block['text']
        out = []
        for block in resp.get("content", []) or []:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                out.append(block["text"])
        return "\n".join(out).strip()
