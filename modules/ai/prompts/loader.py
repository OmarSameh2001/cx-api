"""Prompt files: plain text with $placeholders and @include lines.

    @include shared/language     on its own line, replaced by that file
                                 (relative to modules/ai/prompts, no .md)
    $name / ${name}              filled by render(); $$ is a literal $

`$` placeholders (string.Template) are used instead of {name} so prompts
can contain JSON without escaping braces.
"""

import re
from functools import lru_cache
from pathlib import Path
from string import Template


SHARED_ROOT = Path(__file__).parent
_INCLUDE = re.compile(r"^@include[ \t]+(\S+)[ \t]*$", re.MULTILINE)
_MAX_DEPTH = 5


class PromptError(ValueError):
    pass


def _expand(text: str, depth: int) -> str:
    if depth > _MAX_DEPTH:
        raise PromptError("@include nested too deep (a file includes itself?)")
    return _INCLUDE.sub(
        lambda m: _read(SHARED_ROOT / f"{m.group(1)}.md", depth + 1), text
    )


def _read(path: Path, depth: int = 0) -> str:
    if not path.is_file():
        raise PromptError(f"Prompt file not found: {path}")
    return _expand(path.read_text(encoding="utf-8").strip(), depth)


@lru_cache
def load(path: Path) -> Template:
    """The prompt at `path` with includes resolved; read once per process."""
    return Template(_read(path))


def render(path: Path, **values: object) -> str:
    """Fill the placeholders. A placeholder without a value raises, so a
    typo fails here instead of reaching the model as "$constraints"."""
    try:
        return load(path).substitute({k: str(v) for k, v in values.items()})
    except KeyError as e:
        raise PromptError(f"{path.name}: no value for ${e.args[0]}") from e
    except ValueError as e:
        raise PromptError(f"{path.name}: {e}") from e


class PromptDir:
    """A feature's prompts folder: PromptDir(__file__).render("system")."""

    def __init__(self, anchor: str):
        self.root = Path(anchor).parent

    def render(self, name: str, **values: object) -> str:
        return render(self.root / f"{name}.md", **values)


# modules/ai/prompts itself: shared.render("shared/fix", error=...)
shared = PromptDir(__file__)
