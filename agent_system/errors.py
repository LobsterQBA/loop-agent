"""Render failures for model observations and durable turn records."""


def describe_exception(exc: BaseException) -> str:
    try:
        detail = str(exc)
    except Exception:  # noqa: BLE001 - formatting must not mask the original failure
        detail = "<exception message unavailable>"
    # Tool messages and SQLite records both require UTF-8 encodable text.
    return f"{type(exc).__name__}: {detail}".encode("utf-8", errors="backslashreplace").decode()
