"""The page reader now lives in `app.services.rag.web_page`; this is where the web connector finds it."""

from app.services.rag.web_page import ParsedPage, parse_page

__all__ = ["ParsedPage", "parse_page"]
