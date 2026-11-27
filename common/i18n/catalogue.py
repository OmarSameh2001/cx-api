"""Message catalogues: messages/<locale>/<category>.json.

Each file holds {"name": "text with {placeholders}"}; the message's code is
"<category>.<name>" (auth.invalid_credentials). Files are read once, at the
first lookup.

Older code raises plain English text (HTTPException(404, "Form not found")).
`match` finds the en entry that text came from, placeholders included, so
those messages get a code and a translation without changing every raise.
"""

import json
import re
import string
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from .locales import DEFAULT_LOCALE, LOCALES

MESSAGES_DIR = Path(__file__).parent / "messages"

_lock = threading.Lock()
_catalogues: Optional[dict[str, dict[str, str]]] = None
_exact: dict[str, str] = {}
_patterns: list[tuple[re.Pattern[str], str]] = []


def _read(locale: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    folder = MESSAGES_DIR / locale
    for path in sorted(folder.glob("*.json")):
        category = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, text in data.items():
            if not isinstance(text, str):
                raise ValueError(f"{path}: {name} must be a string")
            entries[f"{category}.{name}"] = text
    return entries


def _pattern(template: str) -> Optional[re.Pattern[str]]:
    parts: list[str] = []
    names: set[str] = set()
    for literal, field, _spec, _conv in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if field is not None:
            if not field.isidentifier() or field in names:
                return None
            names.add(field)
            parts.append(f"(?P<{field}>.+?)")
    if not names:
        return None
    return re.compile("^" + "".join(parts) + "$", re.DOTALL)


def _load() -> dict[str, dict[str, str]]:
    global _catalogues
    if _catalogues is None:
        with _lock:
            if _catalogues is None:
                loaded = {code: _read(code) for code in LOCALES}
                for code, template in loaded["en"].items():
                    english = template.replace("{{", "{").replace("}}", "}")
                    pattern = _pattern(template)
                    if pattern is None:
                        _exact.setdefault(english, code)
                    else:
                        _patterns.append((pattern, code))
                # longest first: the most specific template wins
                _patterns.sort(key=lambda p: -len(p[0].pattern))
                _catalogues = loaded
    return _catalogues


def codes() -> set[str]:
    return set(_load()["en"])


def entries(locale: str) -> dict[str, str]:
    return dict(_load().get(locale, {}))


class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return ""


def text(code: str, locale: Optional[str] = None, params: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """The message in `locale` (English when it has none), filled in; None
    for an unknown code."""
    catalogues = _load()
    template = catalogues.get(locale or DEFAULT_LOCALE, {}).get(code) or catalogues["en"].get(code)
    if template is None:
        return None
    try:
        return template.format_map(_Missing({k: "" if v is None else v for k, v in (params or {}).items()}))
    except (ValueError, IndexError):
        return template


def match(english: str) -> Optional[tuple[str, dict[str, str]]]:
    """(code, params) of the en message `english` was made from, or None."""
    _load()
    code = _exact.get(english)
    if code is not None:
        return code, {}
    for pattern, code in _patterns:
        found = pattern.match(english)
        if found:
            return code, found.groupdict()
    return None


def reset_for_tests() -> None:
    global _catalogues
    with _lock:
        _catalogues = None
        _exact.clear()
        _patterns.clear()
