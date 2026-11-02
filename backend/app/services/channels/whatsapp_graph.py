"""WhatsApp Cloud API: the credentials a bot sends with (#2076).

The Graph client joins this module in a later task; for now it holds only the
envelope the rest of the channel layer passes around as the bot's "token".
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class WhatsAppCredentials:
    """A WhatsApp bot's access token and the number it sends from.

    Carried through the channel layer as the bot's "token" - one string, like
    every other platform's - so a reply and a download each have everything they
    need without a second lookup. `unseal_bot_token` composes it from the row;
    nothing else builds one from text. `bot_id` is there so send health can be
    attributed to the bot without the caller threading it alongside.
    """

    bot_id: str
    access_token: str
    phone_number_id: str

    def encode(self) -> str:
        return json.dumps(
            {
                "bot_id": self.bot_id,
                "access_token": self.access_token,
                "phone_number_id": self.phone_number_id,
            }
        )

    @classmethod
    def decode(cls, token: str) -> WhatsAppCredentials:
        """Read what `encode` wrote.

        Raises:
            ValueError: If the string is not an envelope `encode` wrote, for
                example one that is not JSON or lacks a field.
        """
        try:
            data = json.loads(token)
            return cls(
                bot_id=str(data["bot_id"]),
                access_token=str(data["access_token"]),
                phone_number_id=str(data["phone_number_id"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("A WhatsApp bot's credentials are not readable") from exc
