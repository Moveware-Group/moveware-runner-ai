"""
Enhanced logging system for AI Runner.

Provides structured logging with context, performance tracking, and better debugging.
"""
import logging
import json
import sys
from typing import Any, Dict, Optional
from datetime import datetime
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """
    Formats log messages as structured JSON for better parsing.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, "run_id"):
            log_data["run_id"] = record.run_id
        if hasattr(record, "issue_key"):
            log_data["issue_key"] = record.issue_key
        if hasattr(record, "worker_id"):
            log_data["worker_id"] = record.worker_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "context"):
            log_data["context"] = record.context
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class HumanReadableFormatter(logging.Formatter):
    """
    Formats log messages for human readability.
    """
    
    # Color codes for different log levels
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        # Add color if terminal supports it
        color = self.COLORS.get(record.levelname, '')
        reset = self.RESET if color else ''
        
        # Build message
        parts = [
            f"{color}[{record.levelname}]{reset}",
            datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
        ]
        
        # Add context fields
        if hasattr(record, "run_id"):
            parts.append(f"run={record.run_id}")
        if hasattr(record, "issue_key"):
            parts.append(f"issue={record.issue_key}")
        if hasattr(record, "worker_id"):
            parts.append(f"worker={record.worker_id}")
        
        # Add message
        parts.append("-")
        parts.append(record.getMessage())
        
        # Add duration if present
        if hasattr(record, "duration_ms"):
            parts.append(f"({record.duration_ms}ms)")
        
        message = " ".join(parts)
        
        # Add exception if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        
        return message


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "human",  # "human" or "json"
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    Set up enhanced logging.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format ("human" or "json")
        log_file: Optional file path for log output
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger("ai_runner")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    
    if log_format == "json":
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(HumanReadableFormatter())
    
    logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(StructuredFormatter())  # Always use JSON for file
        logger.addHandler(file_handler)
    
    return logger


# Global logger instance
_logger: Optional[logging.Logger] = None


def get_logger() -> logging.Logger:
    """Get or create the global logger."""
    global _logger
    if _logger is None:
        # Read log settings from environment
        import os
        log_level = os.getenv("LOG_LEVEL", "INFO")
        log_format = os.getenv("LOG_FORMAT", "human")
        log_file = os.getenv("LOG_FILE")
        
        _logger = setup_logging(log_level, log_format, log_file)
    
    return _logger


class ContextLogger:
    """
    Logger with context (run_id, issue_key, etc.).
    
    Usage:
        logger = ContextLogger(run_id=123, issue_key="OD-456")
        logger.info("Processing issue")
        logger.error("Failed to process", context={"error": "timeout"})
    """
    
    def __init__(
        self,
        run_id: Optional[int] = None,
        issue_key: Optional[str] = None,
        worker_id: Optional[str] = None
    ):
        self.run_id = run_id
        self.issue_key = issue_key
        self.worker_id = worker_id
        self.logger = get_logger()
    
    def _log(self, level: str, message: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Internal logging method."""
        extra = {}
        
        if self.run_id is not None:
            extra["run_id"] = self.run_id
        if self.issue_key is not None:
            extra["issue_key"] = self.issue_key
        if self.worker_id is not None:
            extra["worker_id"] = self.worker_id
        if context:
            extra["context"] = context
        
        # Reserve exc_info for std logging - LogRecord rejects it in extra
        exc_info = kwargs.pop("exc_info", False)
        extra.update(kwargs)
        
        log_func = getattr(self.logger, level.lower())
        log_func(message, extra=extra, exc_info=exc_info)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log("DEBUG", message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log("WARNING", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log("ERROR", message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message."""
        self._log("CRITICAL", message, **kwargs)


def log_performance(operation: str):
    """
    Decorator for performance logging.
    
    Usage:
        @log_performance("process_issue")
        def process_issue(issue_key):
            ...
    """
    import time
    
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger()
            start = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.time() - start) * 1000)
                logger.info(
                    f"{operation} completed",
                    extra={"duration_ms": duration_ms}
                )
                return result
            except Exception as e:
                duration_ms = int((time.time() - start) * 1000)
                logger.error(
                    f"{operation} failed: {e}",
                    extra={"duration_ms": duration_ms},
                    exc_info=True
                )
                raise
        
        return wrapper
    return decorator
