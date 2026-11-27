"""The languages the app speaks.

To add a language: add one Locale below and a folder
common/i18n/messages/<code>/ with the same files and keys as en/
(tests/test_i18n.py fails until every key is there).
"""

import os
from dataclasses import dataclass
from typing import Literal, Optional

from dotenv import load_dotenv

load_dotenv()

Direction = Literal["ltr", "rtl"]


@dataclass(frozen=True)
class Locale:
    code: str
    name: str  # in its own language, for a language switch
    direction: Direction


LOCALES: dict[str, Locale] = {
    "en": Locale("en", "English", "ltr"),
    "ar": Locale("ar", "العربية", "rtl"),
}

# the language used when the caller asks for none we speak
DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en").strip().lower()
if DEFAULT_LOCALE not in LOCALES:
    DEFAULT_LOCALE = "en"


def normalize(value: Optional[str]) -> Optional[str]:
    """"ar-EG", "AR", "ar_SA" -> "ar"; None for a language we don't speak."""
    if not value:
        return None
    short = value.strip().replace("_", "-").split("-")[0].lower()
    return short if short in LOCALES else None


def from_accept_language(header: Optional[str]) -> Optional[str]:
    """The best language we speak from an Accept-Language header, honouring
    q-values ("fr;q=0.9, ar;q=0.8" -> "ar"); None if there is none."""
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")[:20]):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                quality = float(params[2:])
            except ValueError:
                quality = 0.0
        code = normalize(tag)
        if code and quality > 0:
            ranked.append((-quality, position, code))
    return min(ranked)[2] if ranked else None
