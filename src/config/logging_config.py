"""
Logging configuration.

Why this exists
---------------
main.py runs `command.upgrade()` inside the lifespan. That imports alembic's
env.py, which calls logging.fileConfig(alembic.ini) — inside our process. A
stock alembic.ini contains:

    [logger_root]
    level = WARN
    handler = console

Our agents do `logging.getLogger(...)` and never set a level of their own, so
their effective level is inherited from root → WARN → every logger.info() is
dropped before it reaches a handler. `alembic.runtime.migration` still printed
because alembic.ini sets *that* logger to INFO explicitly.

This is the sibling of the Phase B disable_existing_loggers bug: that fix
stopped alembic from disabling our loggers, this one stops it from muting them.

configure_logging() MUST be called AFTER command.upgrade(), or fileConfig runs
last and wins.
"""
from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s  %(name)-28s %(levelname)-7s %(message)s"
_DATEFMT = "%H:%M:%S"

# Libraries that are chatty at INFO. Root goes to INFO so our agents are heard;
# these get pinned back to WARNING so the console stays readable.
_NOISY = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "asyncio": logging.WARNING,
    "watchfiles": logging.WARNING,
    "python_multipart": logging.WARNING,
}


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)

    # Alembic's fileConfig normally leaves a console handler on root and we
    # reuse it (its format is what you already see in the uvicorn output).
    # If nothing configured one — e.g. under pytest, where the lifespan may
    # not run — install our own so records aren't swallowed.
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        root.addHandler(handler)

    for name, lvl in _NOISY.items():
        logging.getLogger(name).setLevel(lvl)