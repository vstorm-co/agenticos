"""How a retrieval run is scored and reported, as pure functions over its results.

Three retrieval numbers per category, each over the `top_k` chunks one search
returned, in rank order:

- **hit@k** - the share of questions with at least one chunk from an expected
  page. What the issue that started this (#2482) asks: did the page that says
  "No SAML" reach the model at all.
- **recall@k** - the share of a question's expected pages that were reached,
  averaged. Equal to hit@k for a question with one expected page.
- **MRR** - the mean of 1/rank of the first chunk from an expected page, 0 when
  none was returned. A page found at rank 5 of 5 counts, and counts for little.

The answer check is deliberately crude: every fact group must appear in the
answer as a whole word (or a word beginning with it, for an alternative ending
in `*`). It cannot tell a correct "No" from a confused one, so it is a floor
under the retrieval numbers rather than a grade; the item and the answer are in
the JSON output for anyone who wants to read them.
"""

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

from dataset import CATEGORIES, Dataset, Item

_CITATION = re.compile(r"\[\d+(?:\s*[,-]\s*\d+)*\]")


@dataclass(frozen=True)
class Retrieved:
    """One returned chunk: the page key it came from and its text."""

    page: str
    content: str
    score: float


@dataclass(frozen=True)
class ItemResult:
    """What one question got back, and how it scored."""

    item: Item
    retrieved: tuple[Retrieved, ...]
    answer: str | None = None

    @property
    def first_hit_rank(self) -> int | None:
        """1-based rank of the first chunk from an expected page, or `None`."""
        for rank, chunk in enumerate(self.retrieved, start=1):
            if chunk.page in self.item.expected_pages:
                return rank
        return None

    @property
    def hit(self) -> bool:
        return self.first_hit_rank is not None

    @property
    def recall(self) -> float:
        found = {chunk.page for chunk in self.retrieved} & set(self.item.expected_pages)
        return len(found) / len(self.item.expected_pages)

    @property
    def reciprocal_rank(self) -> float:
        rank = self.first_hit_rank
        return 0.0 if rank is None else 1.0 / rank

    @property
    def missing_facts(self) -> tuple[tuple[str, ...], ...] | None:
        """The fact groups the answer lacks; `None` when it cannot be judged.

        That is when nothing was answered, and when the item names no facts: an
        item without an oracle would otherwise count every answer as correct.
        """
        if self.answer is None or not self.item.expected_facts:
            return None
        # A citation marker is not a fact: "[5]" must not answer "five".
        text = _CITATION.sub(" ", self.answer)
        return tuple(
            group
            for group in self.item.expected_facts
            if not any(mentions(text, alt) for alt in group)
        )

    @property
    def answer_correct(self) -> bool | None:
        missing = self.missing_facts
        return None if missing is None else not missing


def mentions(text: str, alternative: str) -> bool:
    """Whether `text` contains `alternative` as a whole word, case-insensitively.

    A trailing `*` makes it a prefix - `Keycloak*` matches "Keycloaka" - for the
    inflected forms a Polish answer uses. "Whole word" is judged at the edges
    of the alternative only, so `SKILL.md` and `100,000` match as written.
    """
    prefix = alternative.endswith("*")
    body = re.escape(alternative.rstrip("*"))
    pattern = rf"(?<!\w){body}" if prefix else rf"(?<!\w){body}(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


@dataclass(frozen=True)
class Summary:
    """One category's numbers, or every item's under `category="all"`."""

    category: str
    questions: int
    hit_rate: float
    recall: float
    mrr: float
    answered: int
    answers_correct: int


def summarize(results: Sequence[ItemResult]) -> list[Summary]:
    """Per-category rows in a fixed order, then the overall row; empty categories are left out."""
    groups = [
        (category, [r for r in results if r.item.category == category]) for category in CATEGORIES
    ]
    summaries: list[Summary] = []
    for name, members in [*groups, ("all", list(results))]:
        if not members:
            continue
        count = len(members)
        judged = [r.answer_correct for r in members if r.answer_correct is not None]
        summaries.append(
            Summary(
                category=name,
                questions=count,
                hit_rate=sum(r.hit for r in members) / count,
                recall=sum(r.recall for r in members) / count,
                mrr=sum(r.reciprocal_rank for r in members) / count,
                answered=len(judged),
                answers_correct=sum(judged),
            )
        )
    return summaries


Retrieve = Callable[[Item], Awaitable[list[Retrieved]]]
Answer = Callable[[Item, list[Retrieved]], Awaitable[str]]


async def evaluate(
    dataset: Dataset, retrieve: Retrieve, answer: Answer | None = None
) -> list[ItemResult]:
    """Run every item through `retrieve`, and through `answer` when given.

    One item at a time, in file order: a run is a measurement, and firing every
    question at once would measure the provider's rate limit instead.
    """
    results: list[ItemResult] = []
    for item in dataset.items:
        retrieved = await retrieve(item)
        text = None if answer is None else await answer(item, retrieved)
        results.append(ItemResult(item=item, retrieved=tuple(retrieved), answer=text))
    return results


def render_markdown(label: str, results: Sequence[ItemResult]) -> str:
    """One configuration's table, then the questions it missed."""
    summaries = summarize(results)
    answers = any(s.answered for s in summaries)
    header = "| Category | Questions | hit@k | recall@k | MRR |" + (
        " Answers correct |" if answers else ""
    )
    rule = "|---|---:|---:|---:|---:|" + ("---:|" if answers else "")
    lines = [f"### {label}", "", header, rule]
    for s in summaries:
        row = f"| {s.category} | {s.questions} | {s.hit_rate:.0%} | {s.recall:.0%} | {s.mrr:.2f} |"
        if answers:
            row += f" {s.answers_correct}/{s.answered} |"
        lines.append(row)
    missed = [r for r in results if not r.hit]
    if missed:
        lines += ["", "Missed (no chunk from an expected page):", ""]
        for r in missed:
            got = ", ".join(dict.fromkeys(chunk.page for chunk in r.retrieved)) or "nothing"
            lines.append(f"- `{r.item.id}` wanted {', '.join(r.item.expected_pages)}; got {got}")
    wrong = [r for r in results if r.answer_correct is False]
    if wrong:
        lines += ["", "Answers missing an expected fact:", ""]
        for r in wrong:
            lacking = "; ".join(" / ".join(group) for group in r.missing_facts or ())
            lines.append(f"- `{r.item.id}` lacks {lacking}")
    return "\n".join(lines) + "\n"


def as_json(
    label: str,
    top_k: int,
    mode: str,
    results: Sequence[ItemResult],
    *,
    queries: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """One configuration's results in a shape a later run can be diffed against.

    `queries` is what the mode searched for each item id - `multi_query`'s
    question and its rephrasings, `hyde`'s passage. An item's `queries` is
    `null` when the mode generated nothing (`off`).
    """
    return {
        "label": label,
        "top_k": top_k,
        "query_analysis_mode": mode,
        "summary": [asdict(s) for s in summarize(results)],
        "items": [
            {
                "id": r.item.id,
                "category": r.item.category,
                "hit": r.hit,
                "first_hit_rank": r.first_hit_rank,
                "retrieved_pages": [chunk.page for chunk in r.retrieved],
                "answer": r.answer,
                "answer_correct": r.answer_correct,
                "queries": None if queries is None else list(queries.get(r.item.id, ())),
            }
            for r in results
        ],
    }
