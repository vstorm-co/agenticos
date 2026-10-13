"""How an artifact's page reaches a browser - the one place its headers are set.

The page is agent-authored HTML with script in it, which the workspace routes
refuse to serve inline for exactly that reason. Here it is the product, so it is
served inline and the isolation moves into the headers: the `sandbox` policy
gives the document an opaque origin whatever address it was loaded from, and
the source list keeps it self-contained.
"""

from fastapi import Response, status

from app.services.artifact import EmbedDocument, ServedArtifact, content_security_policy


def artifact_response(served: ServedArtifact) -> Response:
    """One rendered artifact version as an HTTP response."""
    return Response(
        content=served.document,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": content_security_policy(embed_origins=served.embed_origins),
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


def library_response(data: bytes, media_type: str) -> Response:
    """One file of the library set, cached for a year: its name carries its version."""
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable",
            # Loaded by a page in an opaque origin, which is cross-origin to
            # everything - `same-origin` here would refuse every page it is for.
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


def embed_response(embed: EmbedDocument) -> Response:
    """The embed document, under a policy naming the sites allowed to frame it."""
    return Response(
        content=embed.document,
        media_type="text/html; charset=utf-8",
        status_code=status.HTTP_200_OK if embed.available else status.HTTP_404_NOT_FOUND,
        headers={
            "Content-Security-Policy": embed.policy,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # It frames a fresh signed address each time; a cached copy would
            # frame one that has expired.
            "Cache-Control": "private, no-store",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
