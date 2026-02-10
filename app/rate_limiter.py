"""
Rate limiting for API calls and worker operations.

Prevents overloading external services (Jira, GitHub, LLMs).
"""
import time
from typing import Dict, Optional
from dataclasses import dataclass
import threading


@dataclass
class RateLimit:
    """Rate limit configuration."""
    calls: int  # Number of calls
    period: float  # Time period in seconds
    

class RateLimiter:
    """
    Token bucket rate limiter.
    
    Thread-safe implementation for multi-worker environments.
    """
    
    def __init__(self, calls: int, period: float):
        """
        Initialize rate limiter.
        
        Args:
            calls: Number of calls allowed
            period: Time period in seconds
        """
        self.calls = calls
        self.period = period
        self.tokens = calls
        self.last_update = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to acquire
            blocking: If True, wait until tokens available
            timeout: Maximum time to wait (None = infinite)
        
        Returns:
            True if acquired, False if not available (when blocking=False)
        """
        start_time = time.time()
        
        while True:
            with self.lock:
                now = time.time()
                
                # Refill tokens based on elapsed time
                elapsed = now - self.last_update
                self.tokens = min(self.calls, self.tokens + (elapsed * self.calls / self.period))
                self.last_update = now
                
                # Try to acquire
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                # If non-blocking, return immediately
                if not blocking:
                    return False
                
                # Check timeout
                if timeout is not None and (now - start_time) >= timeout:
                    return False
            
            # Wait a bit before retry
            time.sleep(0.1)
    
    def get_wait_time(self) -> float:
        """Get estimated wait time for next token."""
        with self.lock:
            if self.tokens >= 1:
                return 0.0
            return (1 - self.tokens) * self.period / self.calls


# Global rate limiters for different services
_rate_limiters: Dict[str, RateLimiter] = {}
_lock = threading.Lock()


def get_rate_limiter(service: str, calls: int, period: float) -> RateLimiter:
    """
    Get or create a rate limiter for a service.
    
    Args:
        service: Service name (e.g., "jira", "github", "claude")
        calls: Number of calls allowed
        period: Time period in seconds
    
    Returns:
        RateLimiter instance
    """
    global _rate_limiters
    
    with _lock:
        if service not in _rate_limiters:
            _rate_limiters[service] = RateLimiter(calls, period)
        return _rate_limiters[service]


# Pre-configured rate limiters
def get_jira_rate_limiter() -> RateLimiter:
    """Jira Cloud rate limit: ~100 requests per minute per user."""
    return get_rate_limiter("jira", calls=80, period=60)


def get_github_rate_limiter() -> RateLimiter:
    """GitHub API rate limit: ~5000 requests per hour."""
    return get_rate_limiter("github", calls=100, period=60)


def get_claude_rate_limiter() -> RateLimiter:
    """Claude API rate limit: ~50 requests per minute (tier dependent)."""
    return get_rate_limiter("claude", calls=40, period=60)


def get_openai_rate_limiter() -> RateLimiter:
    """OpenAI API rate limit: ~500 requests per minute (tier dependent)."""
    return get_rate_limiter("openai", calls=100, period=60)


def rate_limited(service: str, calls: int = 1):
    """
    Decorator for rate-limited functions.
    
    Usage:
        @rate_limited("jira", calls=1)
        def get_issue(issue_key):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter(service, calls=50, period=60)  # Default limits
            limiter.acquire(tokens=calls, blocking=True)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def with_rate_limit(service: str, operation_name: str = "operation"):
    """
    Context manager for rate-limited operations.
    
    Usage:
        with with_rate_limit("jira", "get_issue"):
            result = jira_client.get_issue(key)
    """
    class RateLimitContext:
        def __enter__(self):
            limiter = None
            if service == "jira":
                limiter = get_jira_rate_limiter()
            elif service == "github":
                limiter = get_github_rate_limiter()
            elif service == "claude":
                limiter = get_claude_rate_limiter()
            elif service == "openai":
                limiter = get_openai_rate_limiter()
            
            if limiter:
                wait_time = limiter.get_wait_time()
                if wait_time > 0:
                    print(f"Rate limit: waiting {wait_time:.1f}s for {service} {operation_name}")
                limiter.acquire(tokens=1, blocking=True)
            
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
    
    return RateLimitContext()
