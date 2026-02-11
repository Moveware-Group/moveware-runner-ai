from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, TypeVar, Callable

import requests


T = TypeVar('T')


class AnthropicAPIError(RuntimeError):
    """Raised when Anthropic API returns an error. Holds response for Retry-After."""
    def __init__(self, message: str, status_code: int = 0, response: Optional[requests.Response] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 5,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.5,
    max_delay: float = 120.0
) -> T:
    """
    Retry function with exponential backoff.
    
    Handles rate limits (429), service errors (502/503/504), timeouts,
    and connection errors. Uses Retry-After header when API provides it.
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            error_msg = str(e).lower()
            
            # Retry on: rate limits, service errors, timeouts, connection issues
            should_retry = (
                "rate" in error_msg or 
                "429" in error_msg or 
                "502" in error_msg or
                "503" in error_msg or
                "504" in error_msg or
                "timeout" in error_msg or
                "timed out" in error_msg or
                "overloaded" in error_msg or
                "connection" in error_msg or
                "connectionerror" in error_msg or
                "connection reset" in error_msg or
                "connection refused" in error_msg or
                "service unavailable" in error_msg or
                "bad gateway" in error_msg or
                "gateway timeout" in error_msg
            )
            
            if should_retry and attempt < max_retries - 1:
                # Honor Retry-After header if present (Anthropic sends this for 429)
                actual_delay = delay
                resp = getattr(e, "response", None)
                if resp is not None and hasattr(resp, "headers"):
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            actual_delay = min(float(retry_after), max_delay)
                        except ValueError:
                            pass
                
                print(f"Transient error (attempt {attempt + 1}/{max_retries}): {str(e)[:150]}...")
                print(f"Retrying in {actual_delay:.0f}s...")
                time.sleep(actual_delay)
                delay = min(delay * backoff_factor, max_delay)
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
            # 300s timeout for extended thinking (can take several minutes)
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=300)
            if r.status_code >= 400:
                raise AnthropicAPIError(
                    f"Anthropic error {r.status_code}: {r.text[:500]}",
                    status_code=r.status_code,
                    response=r
                )
            return r.json()
        
        return retry_with_backoff(_make_request, max_retries=5)

    @staticmethod
    def extract_text(resp: Dict[str, Any]) -> str:
        # content is a list of blocks; for text blocks, block['text']
        out = []
        for block in resp.get("content", []) or []:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                out.append(block["text"])
        return "\n".join(out).strip()
