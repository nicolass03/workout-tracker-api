import json
import logging
from typing import Any


validation_logger = logging.getLogger("workout_tracker.validation")


def log_validation_failure(
    *, request_id: str,
    method: str,
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    """Log validation failures without recording a user's request body or GPS data."""
    safe_errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "code": error.get("type"),
            "message": error.get("msg"),
        }
        for error in errors
    ]
    validation_logger.warning(
        json.dumps(
            {
                "event": "request_validation_failed",
                "request_id": request_id,
                "method": method,
                "path": path,
                "errors": safe_errors,
            },
            separators=(",", ":"),
        )
    )
