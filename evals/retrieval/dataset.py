"""The question set: what a retrieval evaluation asks, and what counts as found.

A page is named by its *page key*: its path under `docs/` with the locale suffix
taken off, so `directory.md`, `directory.pl.md` and `directory.de.md` are all
`directory.md`. A retrieved chunk from any translation of an expected page is a
hit. Which translations are in reach is the corpus's business, not the item's:
a `cross_language` item names the one locale it is searched in, which is never
the language it is asked in, and that is what makes it cross-language.

The file is versioned. A change to what a field means bumps `version`, so a
result quoted against version 1 is never silently compared with one measured
against a different question set.
"""

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

Category = Literal["factual", "negative", "cross_language"]
Locale = Literal["en", "pl", "de", "es"]

CATEGORIES: tuple[Category, ...] = ("factual", "negative", "cross_language")
_SUFFIX_LOCALES: dict[str, Locale] = {"pl": "pl", "de": "de", "es": "es"}

# A page key starts with a letter or digit and is a relative `.md` path: no
# leading slash, no `..`, nothing that could name a file outside `docs/`.
_PAGE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.md$")


def page_key(path: str) -> tuple[str, Locale]:
    """A docs-relative path as its page key and the locale it is written in.

    `howto/translate.pl.md` is `("howto/translate.md", "pl")`; a path with no
    locale suffix is English.
    """
    pure = PurePosixPath(path)
    parts = pure.name.split(".")
    if len(parts) >= 3 and parts[-1] == "md" and parts[-2] in _SUFFIX_LOCALES:
        return str(pure.with_name(".".join([*parts[:-2], "md"]))), _SUFFIX_LOCALES[parts[-2]]
    return str(pure), "en"


def localized_path(key: str, locale: Locale) -> str:
    """The file a page key names in one locale: `directory.md` in `pl` is `directory.pl.md`."""
    if locale == "en":
        return key
    return f"{key[: -len('.md')]}.{locale}.md"


UNPUBLISHED: tuple[str, ...] = (
    "design/",
    "plans/",
    "audits/",
    "ROADMAP.md",
    "about/design.md",
    "assets/screens/README.md",
)
"""What `mkdocs.yml`'s `exclude_docs` keeps off the site, and so out of the corpus.

Plans and design notes describe what was intended, often in the words a question
uses, and a reader of the published docs never sees them. The two lists are
held equal by `backend/tests/test_retrieval_eval.py`.
"""


EVAL_PAGES: tuple[str, ...] = ("retrieval-eval.md",)
"""Published, and left out of the corpus anyway.

The page that documents this evaluation quotes its questions and their answers
word for word, so in the corpus it would outrank the page each answer is on.
"""


def is_published(relative: str) -> bool:
    """Whether a docs-relative path is a page the site publishes."""
    key, _locale = page_key(relative)
    return not any(
        key.startswith(rule) if rule.endswith("/") else key == rule for rule in UNPUBLISHED
    )


def corpus_files(docs_root: Path, locale: Locale) -> list[Path]:
    """Every published page under `docs_root` written in `locale`, in path order.

    This evaluation's own page (`EVAL_PAGES`) is left out.
    """
    pages = [
        (path, page_key(path.relative_to(docs_root).as_posix())) for path in docs_root.rglob("*.md")
    ]
    return sorted(
        path
        for path, (key, written_in) in pages
        if written_in == locale and key not in EVAL_PAGES and is_published(key)
    )


class Item(BaseModel):
    """One question and where its answer is written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    category: Category
    language: Locale
    search_locales: tuple[Locale, ...] | None = None
    """The corpus locales this item is searched in; `None` searches them all."""
    question: str = Field(min_length=1)
    expected_pages: tuple[str, ...] = Field(min_length=1)
    expected_facts: tuple[tuple[str, ...], ...] = ()
    """What a correct answer contains: every group must match, any one of its alternatives."""
    evidence: str = ""
    """The sentence on the expected page that answers it, for whoever reviews the item."""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.expected_pages)) != len(self.expected_pages):
            raise ValueError("an expected page is listed twice")
        for page in self.expected_pages:
            key, locale = page_key(page)
            if locale != "en" or key != page or not _matches_page_key(page):
                raise ValueError(f"expected page {page!r} is not a page key")
            if not is_published(page):
                raise ValueError(
                    f"expected page {page!r} is not published, so it is not in the corpus"
                )
        if any(
            not group or not all(alternative.strip() for alternative in group)
            for group in self.expected_facts
        ):
            raise ValueError("an expected fact group is empty")
        if any(
            alternative.endswith("*") and not alternative.rstrip("*").strip()
            for group in self.expected_facts
            for alternative in group
        ):
            raise ValueError("an expected fact wildcard has an empty stem")
        if self.category == "cross_language":
            if not self.search_locales:
                raise ValueError("a cross_language item names the locales it is searched in")
            if self.language in self.search_locales:
                raise ValueError("a cross_language item is not searched in its own language")
        elif self.search_locales is not None:
            raise ValueError("only a cross_language item narrows the locales it is searched in")
        return self


def _matches_page_key(page: str) -> bool:
    return _PAGE_KEY.fullmatch(page) is not None and ".." not in PurePosixPath(page).parts


class DatasetError(ValueError):
    """A question set the harness refuses, with one message saying which item and why."""


class Dataset(BaseModel):
    """A versioned list of items with unique ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    items: tuple[Item, ...] = Field(min_length=1)
    _sha256: str = PrivateAttr(default="")

    @property
    def sha256(self) -> str:
        """SHA-256 of the file's bytes as `load_dataset` read them; empty for a set built in code."""
        return self._sha256

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: set[str] = set()
        for item in self.items:
            if item.id in seen:
                raise ValueError(f"item id {item.id!r} appears twice")
            seen.add(item.id)
        return self


def load_dataset(
    path: Path, *, docs_root: Path | None = None, locales: tuple[Locale, ...] = ("en",)
) -> Dataset:
    """Read and validate a question set.

    With `docs_root`, also refuse an item whose expected page could not be
    found: one missing in English, or missing from every locale the item is
    searched in - its `search_locales`, or else the run's `locales`. A page
    renamed or untranslated under `docs/` would otherwise score as a miss for a
    reason that has nothing to do with retrieval.

    Raises:
        DatasetError: The file cannot be read, is not UTF-8 YAML, is not a
            valid question set, or names a page that is not there. The
            message names the file and, for each problem, the item it is in.
    """
    try:
        content = path.read_bytes()
    except OSError as error:
        raise DatasetError(f"{path} cannot be read: {error.strerror or error}") from None
    try:
        raw = yaml.safe_load(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise DatasetError(
            f"{path} is not UTF-8 text: {error.reason} at byte {error.start}"
        ) from None
    except yaml.YAMLError as error:
        raise DatasetError(f"{path} is not YAML: {error}") from None
    try:
        dataset = Dataset.model_validate(raw)
    except ValidationError as error:
        raise DatasetError(
            f"{path} is not a valid question set:\n  " + "\n  ".join(_problems(error, raw))
        ) from None
    if docs_root is not None:

        def exists(page: str, locale: Locale) -> bool:
            return (docs_root / localized_path(page, locale)).is_file()

        missing = [
            f"{item.id}: {page} in {', '.join(searched)}"
            for item in dataset.items
            for searched in [item.search_locales or locales]
            for page in item.expected_pages
            if not exists(page, "en") or not any(exists(page, locale) for locale in searched)
        ]
        if missing:
            raise DatasetError(
                f"{path}: expected pages missing under docs/: " + "; ".join(sorted(missing))
            )
    dataset._sha256 = hashlib.sha256(content).hexdigest()
    return dataset


def _problems(error: ValidationError, raw: object) -> list[str]:
    """Each validation error as `item <id>[, <field>]: <what is wrong>`.

    pydantic drops an item that failed and then checks the length of what is
    left, so a set whose only item is refused also reports `items` as empty.
    That second error is a consequence of the first, and is left out.
    """
    errors = error.errors(include_url=False)
    an_item_failed = any(len(e["loc"]) > 1 and e["loc"][0] == "items" for e in errors)
    problems: list[str] = []
    for e in errors:
        loc = e["loc"]
        if an_item_failed and loc == ("items",) and e["type"] == "too_short":
            continue
        where: list[str] = []
        if len(loc) > 1 and loc[0] == "items" and isinstance(loc[1], int):
            where.append(f"item {_item_label(raw, loc[1])}")
            loc = loc[2:]
        if loc:
            where.append(".".join(str(part) for part in loc))
        cause = e.get("ctx", {}).get("error")
        message = str(cause) if e["type"] == "value_error" and cause is not None else e["msg"]
        problems.append(f"{', '.join(where)}: {message}" if where else message)
    return problems


def _item_label(raw: object, index: int) -> str:
    """The item's id as written, or its 1-based position when it has none."""
    items = raw.get("items") if isinstance(raw, dict) else None
    entry = items[index] if isinstance(items, list) and index < len(items) else None
    identifier = entry.get("id") if isinstance(entry, dict) else None
    return identifier if isinstance(identifier, str) and identifier else f"#{index + 1}"
