"""Logging configuration for the backend.

One `configure_logging()` call sets up an `app.*` logger namespace so
every module can do:

    logger = logging.getLogger("app.something")

and have the output land on stdout with a consistent format. The
function is idempotent — safe to call from `app.main` (when uvicorn
loads it) and again from CLI scripts like `app.scripts.reset_db`
without doubling up handlers.

`sqlalchemy.*` is held at WARNING by default. Flip the
`level=logging.DEBUG` arg, or `getLogger("sqlalchemy.engine")
.setLevel(logging.INFO)`, when you need to see SQL.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: int = logging.INFO) -> None:
    """Wire stdout handler + sensible levels onto the `app.*` namespace."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))

    # Scope the handler to our namespace so we don't fight with
    # uvicorn's own loggers or with pytest's capture machinery.
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    app_logger.addHandler(handler)
    app_logger.propagate = False

    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    _CONFIGURED = True
