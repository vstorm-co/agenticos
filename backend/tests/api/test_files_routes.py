"""What a chat attachment's response says about itself.

The bytes and the authorisation are covered where they are decided; this is the
header, because it is the half that was wrong for every name a Polish keyboard
produces.
"""

from app.api.responses import content_disposition


class TestANameOutsideLatinOne:
    """The 500 that read as a missing file.

    An ASGI server encodes headers as latin-1, so `filename="…"` raised
    `UnicodeEncodeError` on the first character outside it - and the browser was
    shown `FILE_NOT_FOUND` about a file that was there, on preview and on download
    alike. `AI-Engineer-plan-nauki-pełny-eksport.pdf` died on its `ł`.
    """

    def test_the_header_carries_it_percent_encoded(self) -> None:
        header = content_disposition("inline", "AI-Engineer-plan-nauki-pełny-eksport.pdf")

        assert header == "inline; filename*=UTF-8''AI-Engineer-plan-nauki-pe%C5%82ny-eksport.pdf"

    def test_the_header_is_encodable_at_all(self) -> None:
        """The assertion that would have caught it: latin-1, the way the server
        writes it, rather than a comparison in Python's own strings."""
        content_disposition("attachment", "pełny.pdf").encode("latin-1")

    def test_a_quote_or_a_newline_cannot_reach_the_header(self) -> None:
        """The bare form's other problem: both are header-injection primitives,
        and percent-encoding leaves nothing to inject with."""
        header = content_disposition("attachment", 'a"b\nc.csv')

        assert '"' not in header
        assert "\n" not in header
