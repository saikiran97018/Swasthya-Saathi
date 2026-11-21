import logging
import re
import sys

_TOKEN_QS = re.compile(r"(token=)[^&\s\"']+")


class RedactTokens(logging.Filter):
    """The WebSocket URL carries the JWT as ?token=...; uvicorn logs URLs, so scrub it from every log line."""

    @staticmethod
    def _clean(value):
        return _TOKEN_QS.sub(r"\1REDACTED", value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._clean(v) for k, v in record.args.items()}
        return True


def install_log_redaction() -> None:
    """Idempotent. Call after the server has configured its own loggers (i.e. at app startup)."""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in logger.filters):
            logger.addFilter(RedactTokens())
    for handler in logging.getLogger().handlers + logging.getLogger("uvicorn").handlers:
        if not any(isinstance(f, RedactTokens) for f in handler.filters):
            handler.addFilter(RedactTokens())


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_app_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._app_configured = True  # type: ignore[attr-defined]
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
