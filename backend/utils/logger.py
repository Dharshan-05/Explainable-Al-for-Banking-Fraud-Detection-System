import logging
import sys
import json
import re
from datetime import datetime, timezone
from typing import Any
from middleware.request_id import get_request_id

def sanitize_string(text: str) -> str:
    if not isinstance(text, str):
        return text
    # 1. Redact credit card numbers (PAN): 13-19 digits
    text = re.sub(r'\b(?:\d[ -]*?){13,19}\b', '[REDACTED_CARD]', text)
    
    # 2. Redact CVV patterns
    text = re.sub(r'(?i)\bcvv\b\s*[:=]\s*["\']?\d{3,4}["\']?', 'cvv: [REDACTED]', text)
    
    # 3. Redact common secret keys: password, jwt, token, csrf, secret, cvv
    pattern = r'(?i)\b(password|jwt|token|csrf|secret|cvv)\b\s*[:=]\s*["\']?([^\s"\',}]+)["\']?'
    text = re.sub(pattern, r'\1: [REDACTED]', text)
    
    # 4. Redact bearer token headers
    text = re.sub(r'(?i)bearer\s+[a-zA-Z0-9_\-\.\/]+', 'Bearer [REDACTED]', text)
    
    # 5. Redact raw CSV rows if printed in tracebacks or error messages
    text = re.sub(r'(?i)\b(?:amount,time,v1|v1,v2,v3)\b.*', '[REDACTED_CSV_DATA]', text)

    return text

def sanitize_log_value(val: Any) -> Any:
    if val is None:
        return None
    class_name = val.__class__.__name__
    module_name = val.__class__.__module__ or ""
    # Do not serialize raw Request or Response objects
    if "Request" in class_name or "Response" in class_name or "starlette" in module_name or "fastapi" in module_name:
        return f"[REDACTED_{class_name.upper()}]"
        
    if isinstance(val, str):
        return sanitize_string(val)
    elif isinstance(val, dict):
        return {k: sanitize_log_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_log_value(x) for x in val]
    elif isinstance(val, (int, float, bool)):
        return val
    # Fallback to string representation to avoid serialization failure
    try:
        return sanitize_string(str(val))
    except Exception:
        return "[UNSERIALIZABLE_OBJECT]"

class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter that outputs structured logs in JSON format.
    Ensures that timestamp, level, module, message, event_type, request_id,
    and error_category are logged consistently.
    """
    def format(self, record):
        # Base JSON log fields
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "module": record.name,
            "message": sanitize_string(record.getMessage()),
        }

        # Include optional event_type (defaults to "app_event")
        event_type = getattr(record, "event_type", None)
        if event_type:
            log_data["event_type"] = event_type
        else:
            log_data["event_type"] = "app_event"

        # Include correlation request_id if available
        req_id = get_request_id()
        if req_id:
            log_data["request_id"] = req_id

        # Include error_category and trace if exception is present
        if record.exc_info:
            log_data["error_category"] = record.exc_info[0].__name__
            raw_exc = self.formatException(record.exc_info)
            log_data["exception"] = sanitize_string(raw_exc)

        # Merge standard logging extra fields (avoiding standard records)
        standard_fields = {
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module',
            'msecs', 'message', 'msg', 'name', 'pathname', 'process',
            'processName', 'relativeCreated', 'stack_info', 'thread',
            'threadName', 'event_type'
        }
        for key, value in record.__dict__.items():
            if key not in standard_fields:
                log_data[key] = sanitize_log_value(value)

        return json.dumps(log_data)

def setup_logging():
    """Configure the root logger to output structured JSON logs to stdout."""
    from config import settings

    root_logger = logging.getLogger()
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Set up stdout handler with the structured JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # Set root logger log level
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    root_logger.setLevel(level)
