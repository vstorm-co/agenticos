"""The tool the drafts capability exposes.

The public method below is the tool, and its docstring is the only description
of it the model ever reads. Anything else here is a private helper.
"""

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.drafts._spec import (
    DRAFTED,
    WRITE_DRAFT,
    DraftCard,
)
from app.agents.deps import AgentDeps


class DraftFieldInput(BaseModel):
    """One part of a draft. Typed and described, never limited.

    The limits live on `DraftField`, checked inside the tool: a limit here would
    fail in Pydantic AI's argument validation, which ends the run once its
    retries are spent, where `steer` lets the model apologise and carry on.
    """

    name: str | None = Field(
        default=None, description="What this part is, e.g. 'Subject'. Only when there are several."
    )
    text: str = Field(description="The text exactly as it should be pasted.")
    format: str = Field(
        default="text",
        description="'text' unless asked for another: 'markdown', or a language for a snippet.",
    )


class DraftVersionInput(BaseModel):
    """One version of a draft: a label and its parts."""

    label: str | None = Field(
        default=None,
        description="One or two words, shown as the tab. Required with two or more versions.",
    )
    fields: list[DraftFieldInput] = Field(
        description="The parts of this version, one per place it is pasted."
    )


def _explain(exc: ValidationError) -> str:
    """Render a validation failure as something the model can act on."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'draft'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )


class DraftsToolset(FunctionToolset[AgentDeps]):
    """Shows text the person will send elsewhere as a card they copy from.

    The tool draws nothing: the console rebuilds the card from the call's
    arguments. Arguments the model gets wrong come back as `ModelRetry`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_function(self.write_draft, name=WRITE_DRAFT)

    def write_draft(
        self,
        ctx: RunContext[AgentDeps],
        title: str,
        kind: str,
        versions: list[DraftVersionInput],
    ) -> str:
        """Show a draft the person will send or paste somewhere else, as a card they copy from.

        The person sees the card with a copy button on each part, so do not repeat
        the draft in your answer; say at most one short line around it.

        Use this when the person asks for text they will send or paste elsewhere:
        an e-mail, a chat message, a post, an issue or pull request description.
        Write plain text unless they asked for markdown or another format, and
        then set `format` to say so.

        Use square brackets only for a detail the person must fill in, such as
        `[Your Name]` or `[date]`, and never invent such a detail. Keep brackets
        that are already part of text they gave you or that you are replying to,
        such as `Re: [EXTERNAL] ...` or `[WIP]`.

        Make one segment (`fields` entry) per part that is pasted in a different
        place, such as `Subject` and `Body`, and name a field only when there are
        several. Several versions go in one call, each with a one- or two-word
        label such as `Short` and `With details`. Code answers stay in code
        blocks; give a field a `format` like `python` only for a snippet the draft
        itself carries.

        Args:
            title: What the draft is for, e.g. 'Reply to Marta about the Q4 deck'.
            kind: What sort of text it is, e.g. 'Email', 'Slack message', 'Post'.
            versions: One to five versions, each with a label (when there is more
                than one) and its fields.

        Returns:
            A confirmation that the card is on its way to the person.
        """
        for field, value in (("title", title), ("kind", kind)):
            if not value.strip():
                return steer(ctx, f"That draft needs a {field}. Add it and call the tool again.")
        try:
            card = DraftCard.model_validate(
                {
                    "title": title,
                    "kind": kind,
                    "versions": [version.model_dump() for version in versions],
                }
            )
        except ValidationError as exc:
            return steer(
                ctx,
                f"That draft could not be shown ({_explain(exc)}). "
                "Correct the arguments and call the tool again.",
            )
        return (
            f"{DRAFTED}{card.title!r}. The person can already see the draft in full as a "
            f"card: do not write it out again in your answer, and say at most one short line."
        )
