"""LLM-based image description for RAG document processing."""

import base64
import logging
from abc import ABC, abstractmethod

from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

logger = logging.getLogger(__name__)

IMAGE_DESCRIPTION_PROMPT = (
    "Describe this image in detail. Focus on any text, data, charts, diagrams, "
    "or visual information that would be useful for document search and retrieval. "
    "Be concise but comprehensive."
)


class BaseImageDescriber(ABC):
    """Abstract base for LLM-based image description."""

    @abstractmethod
    async def describe(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Generate a text description of an image."""


def _b64_encode(image_bytes: bytes) -> str:
    """Base64-encode raw image bytes."""
    return base64.b64encode(image_bytes).decode("utf-8")


class PydanticAIImageDescriber(BaseImageDescriber):
    """Image description using Pydantic AI.

    Takes a model that has already been built — by
    :class:`app.services.ingestion_config.IngestionConfigService`, from a model
    profile whose credential was unsealed for the organization that owns the
    document. It used to take a model *name* and let Pydantic AI find a key in
    the environment, which on a deployment serving several tenants billed one
    organization's ingestion to a platform-wide key and gave the collection's
    owner no say in which model read their documents.
    """

    def __init__(
        self,
        model: Model,
        *,
        prompt: str = IMAGE_DESCRIPTION_PROMPT,
        model_settings: ModelSettings | None = None,
    ) -> None:
        self.model = model
        self.prompt = prompt
        self.model_settings = model_settings or ModelSettings()

    async def describe(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        try:
            from pydantic_ai import Agent
            from pydantic_ai.messages import BinaryContent

            agent = Agent(self.model, model_settings=self.model_settings)
            result = await agent.run(
                [
                    BinaryContent(data=image_bytes, media_type=mime_type),
                    self.prompt,
                ]
            )
            return result.output if hasattr(result, "output") else str(result.data)
        except Exception as e:
            # One unreadable image must not fail a three-hundred-page document,
            # but the description silently going missing is how "the diagram is
            # not searchable" becomes unexplainable.
            logger.error("Image description failed: %s", e)
            return ""
