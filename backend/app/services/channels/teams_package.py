"""The Teams app package for one bot (#1985).

What an administrator uploads to their tenant's app catalog: a manifest naming
the bot's Azure registration, and the two icons Teams requires. Built here so
nobody hand-writes a manifest - the bot id, the scopes and the commands come
from the row, and the package is valid the first time.
"""

import io
import json
import zipfile
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.db.models.channel_bot import ChannelBot
from app.services.channels.base import CHANNEL_COMMANDS

MANIFEST_SCHEMA = (
    "https://developer.microsoft.com/en-us/json-schemas/teams/v1.19/MicrosoftTeams.schema.json"
)
MANIFEST_VERSION = "1.19"

ACCENT = (91, 76, 219)
"""The tile colour behind the bot's initial."""


def teams_manifest(bot: ChannelBot) -> dict[str, Any]:
    """The manifest: the bot in personal chats, group chats and team channels."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    host = urlparse(base).hostname or "localhost"
    commands = [
        {"title": name, "description": description}
        for name, description in CHANNEL_COMMANDS
        if name not in {"start"}
    ]
    return {
        "$schema": MANIFEST_SCHEMA,
        "manifestVersion": MANIFEST_VERSION,
        "version": "1.0.0",
        "id": bot.teams_app_id,
        "developer": {
            "name": settings.PROJECT_NAME,
            "websiteUrl": base,
            "privacyUrl": f"{base}/legal/privacy",
            "termsOfUseUrl": f"{base}/legal/terms",
        },
        "name": {"short": bot.name[:30], "full": bot.name[:100]},
        "description": {
            "short": f"{bot.name} in {settings.PROJECT_NAME}"[:80],
            "full": (
                f"Ask {bot.name} in a personal chat, mention it in a group chat or a "
                "channel, and approve what it asks to do without leaving Teams."
            ),
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": "#{:02X}{:02X}{:02X}".format(*ACCENT),
        "bots": [
            {
                "botId": bot.teams_app_id,
                "scopes": ["personal", "groupChat", "team"],
                "supportsFiles": True,
                "isNotificationOnly": False,
                "commandLists": [
                    {"scopes": ["personal", "groupChat", "team"], "commands": commands}
                ],
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [host],
    }


def _icon(size: int, *, outline: bool, initial: str) -> bytes:
    """A square tile with the bot's initial: coloured, or white on transparent."""
    background = (0, 0, 0, 0) if outline else (*ACCENT, 255)
    image = Image.new("RGBA", (size, size), background)
    draw = ImageDraw.Draw(image)
    if outline:
        draw.rounded_rectangle(
            (1, 1, size - 2, size - 2), radius=size // 5, outline=(255, 255, 255, 255), width=2
        )
    font = ImageFont.load_default(size=max(10, size // 2))
    draw.text((size / 2, size / 2), initial, fill=(255, 255, 255, 255), font=font, anchor="mm")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def teams_app_package(bot: ChannelBot) -> bytes:
    """The zip Teams installs: `manifest.json`, `color.png` (192 px) and `outline.png` (32 px)."""
    initial = (bot.name.strip()[:1] or "A").upper()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(teams_manifest(bot), indent=2))
        package.writestr("color.png", _icon(192, outline=False, initial=initial))
        package.writestr("outline.png", _icon(32, outline=True, initial=initial))
    return buffer.getvalue()
