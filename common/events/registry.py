"""Who reacts to which event.

A handler is `fn(db, event) -> None`. It runs inside a savepoint of the
relay's transaction and must not commit: its changes and its
processed_events row are saved together, or not at all.

    from common.events.registry import handler

    @handler("submission.graded")
    def open_task_for_low_score(db, event): ...

Modules with handlers are listed in HANDLER_MODULES, so the relay imports
them (and so registers their handlers) before it runs.
"""

import importlib
from typing import Callable

from sqlalchemy.orm import Session

Handler = Callable[[Session, object], None]

# modules whose import registers handlers, e.g. "modules.workflows.handlers"
HANDLER_MODULES: list[str] = ["modules.files.handlers"]

_handlers: dict[str, dict[str, Handler]] = {}
_loaded = False


def handler(event_type: str, name: str | None = None) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        key = name or f"{fn.__module__}.{fn.__name__}"
        _handlers.setdefault(event_type, {})[key] = fn
        return fn

    return register


def handlers_for(event_type: str) -> dict[str, Handler]:
    load_handlers()
    return dict(_handlers.get(event_type, {}))


def load_handlers() -> None:
    global _loaded
    if not _loaded:
        for module in HANDLER_MODULES:
            importlib.import_module(module)
        _loaded = True


def unregister(event_type: str, name: str) -> None:
    _handlers.get(event_type, {}).pop(name, None)
