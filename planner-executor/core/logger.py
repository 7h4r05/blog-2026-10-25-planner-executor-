import json
import sys
from datetime import datetime, timezone


_MISSING = object()


def log(message: str, data: object = _MISSING) -> None:
    timestamp = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

    suffix = "" if data is _MISSING else f" {json.dumps(data)}"
    sys.stderr.write(f"[{timestamp}] {message}{suffix}\n")
