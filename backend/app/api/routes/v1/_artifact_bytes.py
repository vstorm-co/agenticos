"""How an artifact's page reaches a browser - the one place its headers are set.

The page is agent-authored HTML with script in it, which the workspace routes
refuse to serve inline for exactly that reason. Here it is the product, so it is
served inline and the isolation moves into the headers: the `sandbox` policy
gives the document an opaque origin whatever address it was loaded from, and
the source list keeps it self-contained.
"""

from fastapi import Response

from app.services.artifact import content_security_policy


def artifact_response(document: bytes) -> Response:
    """One rendered artifact version as an HTTP response."""
    return Response(
        content=document,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": content_security_policy(),
            "X-Content-Type-Options": "nosniff",
            # The address carries a signed token; a link clicked inside the page
            # must not hand it to wherever the link goes.
            "Referrer-Policy": "no-referrer",
            # Each frame asks for a fresh address, and a shared cache holding a
            # page behind a token that has since expired is a page served to
            # nobody who may still read it.
            "Cache-Control": "private, no-store",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
