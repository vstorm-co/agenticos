"""A path segment that matches every character, line breaks included.

Starlette's `path` convertor is `.*`, which does not match a newline. A request for
`/by-external-id/abc%0A` therefore reached the route as `abc`, because the trailing
`$` of the compiled route accepts the position before a final newline, and the write
landed on the wrong record; `a%0Ab` matched nothing and answered a bare 404 outside
the error envelope. A route that takes free text in its path registers this instead
and refuses what it does not want with a validation error of its own, so a refusal is
a 422 in the one envelope rather than a silent match or a missing route.
"""

from starlette.convertors import Convertor, register_url_convertor


class AnyTextConvertor(Convertor[str]):
    regex = r"[\s\S]*"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


ANYTEXT = "anytext"
"""The convertor's name in a route path: `{external_id:anytext}`."""

register_url_convertor(ANYTEXT, AnyTextConvertor())
