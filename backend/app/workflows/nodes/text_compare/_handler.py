"""`text.compare`: how alike two texts are, as a number from 0 to 1.

A score of 1 means the texts are the same once the settings' differences are
ignored; 0 means they have nothing in common. The method says what is counted:

- `char_ratio`: the share of characters an editor would not have to touch (an
  exact edit distance over characters).
- `token_f1`: the share of words the two texts have in common, order ignored.
- `line_diff`: the share of lines that are unchanged.

The default method is `char_ratio`. By default whitespace is ignored and
nothing else is. Ignoring whitespace collapses the spacing within a line,
trims each line and drops blank lines; line breaks still count, so only
`token_f1`, which counts words, ignores where a line ends. Case, punctuation
and quoted mail with its signature are ignored only when the step is set to.
Composed and decomposed accents are never an edit, and nor are line endings.

Each text is at most 100,000 characters. A longer one ends the run with
`INVALID_BINDING` before the step runs, so `error.handle` cannot route it. A
step with no settings or no texts fails with `TEXT_COMPARE_NOT_CONFIGURED`. The step calls no model and costs nothing; the scoring is
deterministic, so the same two texts always give the same numbers.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from app.services import text_similarity
from app.services.text_similarity import MAX_TEXT_CHARS, Method, Normalization, Unit
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError


class TextCompareConfig(BaseModel):
    """How to score the two texts and what to ignore while doing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Method = Field(
        default="char_ratio",
        title="Method",
        description="What is counted: characters, words in common, or unchanged lines",
    )
    ignore_case: bool = Field(default=False, description="Treat capitals and lower case as equal")
    ignore_whitespace: bool = Field(
        default=True,
        description=(
            "Collapse spacing within a line, trim each line and drop blank lines; "
            "line breaks still count"
        ),
    )
    ignore_punctuation: bool = Field(default=False, description="Leave punctuation out")
    strip_quoted: bool = Field(
        default=False,
        title="Leave out quoted mail and signatures",
        description="Drop quoted reply lines, the attribution and anything after a signature",
    )


class TextCompareInput(BaseModel):
    """The two texts to compare, each at most 100,000 characters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    a: str = Field(max_length=MAX_TEXT_CHARS, description="The first text, such as the original")
    b: str = Field(max_length=MAX_TEXT_CHARS, description="The second text, such as the edit")


class TextCompareOutput(BaseModel):
    """The score, how much changed, and what was counted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(description="How alike the texts are: 1 the same, 0 nothing in common")
    changed_ratio: float = Field(description="How much differs: 1 minus the score")
    method: Method = Field(description="The method that produced the score")
    unit: Unit = Field(description="What the method counted: characters, tokens or lines")
    a_units: int = Field(description="How many units the first text has, after normalising")
    b_units: int = Field(description="How many units the second text has, after normalising")


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, TextCompareConfig) or not isinstance(node_input, TextCompareInput):
        return Failed(
            error=WorkflowError(
                code="TEXT_COMPARE_NOT_CONFIGURED", message="This step needs two texts"
            )
        )
    # Up to a few seconds of CPU at the limit: off the event loop.
    similarity = await asyncio.to_thread(
        text_similarity.compare,
        node_input.a,
        node_input.b,
        method=config.method,
        normalization=Normalization(
            case=config.ignore_case,
            whitespace=config.ignore_whitespace,
            punctuation=config.ignore_punctuation,
            strip_quoted=config.strip_quoted,
        ),
    )
    return Completed[TextCompareOutput](
        output=TextCompareOutput(
            score=similarity.score,
            changed_ratio=similarity.changed_ratio,
            method=similarity.method,
            unit=similarity.unit,
            a_units=similarity.a_units,
            b_units=similarity.b_units,
        )
    )
