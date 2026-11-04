"""A run's resume link: made from its id under the deployment's secret (#1947).

Kept apart from the service that answers it (`resume`), which reaches the
dispatcher: a node handler hands the link on, and nodes load with the registry.
"""

import hashlib
import hmac
from uuid import UUID

from app.core.config import settings


def resume_token(run_id: UUID) -> str:
    """The MAC that makes `run_id`'s resume link: only the deployment can make it."""
    message = f"workflow-resume:{run_id}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def resume_url(run_id: UUID) -> str:
    """The address that resumes `run_id`'s Wait steps waiting for a call."""
    return (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_V1_STR}"
        f"/workflow-resume/{run_id}/{resume_token(run_id)}"
    )
