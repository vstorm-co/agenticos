"""Tool text for the tools this repository does not implement.

A tool written here needs none of this: its docstring *is* its description, and
pydantic-ai wraps a `Returns:` section in `<summary>` and `<returns>` on the way
to the model. That is the shape every capability in this repository sends.

A tool that comes from a library is registered with an explicit `description=`,
which takes that path away - the string is passed through as it stands. Written
by hand, it arrives as a paragraph with the return shape buried in the prose, or
missing, while `create_chart` beside it arrives structured. Two conventions in
one tool list is one more thing for the model to reconcile, for no reason anybody
chose.

So the text handed to a library goes through :class:`ToolText`, which renders
what the framework would have rendered. `tests/test_tool_text_shape.py` pins that
against a tool pydantic-ai builds itself, so a change on that side fails here
rather than leaving these tools speaking a dialect of their own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolText:
    """What the model reads about one tool, in the framework's own shape."""

    summary: str
    """One sentence: what the tool does. Also what the Builder shows a person."""

    usage: str = ""
    """When to use it, when to reach for another tool, and what it will not do."""

    returns: str = ""
    """The shape of the answer - its failures and its truncation included."""

    def render(self, extra: str = "") -> str:
        """The description handed to the library, and through it to the model.

        Args:
            extra: Text appended to the prose before it is wrapped, for the part
                known only once the capability is configured. Inside the summary
                rather than after it, or the tags no longer bracket what they
                claim to.
        """
        parts = [self.summary]
        if self.usage:
            parts.append(self.usage)
        if extra:
            parts.append(extra)
        body = "\n\n".join(parts)
        if not self.returns:
            return body
        return (
            f"<summary>{body}</summary>\n"
            f"<returns>\n<description>{self.returns}</description>\n</returns>"
        )
