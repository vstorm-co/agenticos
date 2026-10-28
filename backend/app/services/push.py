"""Push to everything a person turned notifications on in (#2097): their
browsers and installed PWAs through Web Push (`web_push`), the Android app
through the same, and their iPhones through APNs (`apns`).

The notification sweep and the settings page's test go through here, so a
notification reaches every kind of device and a test proves all of them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import push_subscription as push_repo
from app.repositories import session as session_repo
from app.schemas.push import PushPreferencesRead, PushPreferencesUpdate
from app.services.apns import ApnsService
from app.services.web_push import PushMessage, PushOutcome, WebPushService


class PushService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        web: WebPushService | None = None,
        apple: ApnsService | None = None,
    ):
        self.db = db
        self.web = web or WebPushService(db)
        self.apple = apple or ApnsService(db)

    async def send(self, user_id: uuid.UUID, message: PushMessage) -> PushOutcome:
        """Every browser and every iPhone, outcomes added up."""
        return await self.web.send(user_id, message) + await self.apple.send(user_id, message)

    async def subscribed(self, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Who of these people has anything to push to."""
        return await push_repo.subscribed(self.db, user_ids) | await self.apple.subscribed(user_ids)

    async def send_test(self, user_id: uuid.UUID, *, app_name: str) -> PushOutcome:
        """A push to the caller's own browsers and iPhones, from the settings page."""
        if not await self.web.has_subscriptions(user_id) and not await self.apple.has_devices(
            user_id
        ):
            raise NotFoundError(message="No browser or phone of yours is subscribed to push yet.")
        return await self.send(
            user_id,
            PushMessage(
                title=app_name,
                body="Push works. This is what a notification from your agents looks like.",
                url="/settings/notifications",
                tag="push-test",
            ),
        )

    async def preferences(
        self, user_id: uuid.UUID, session_id: uuid.UUID | None
    ) -> PushPreferencesRead:
        if session_id is None:
            raise NotFoundError(message="Push preferences require a browser or app sign-in.")
        rows = await session_repo.push_preferences_for(
            self.db, user_id=user_id, session_ids=[session_id]
        )
        return PushPreferencesRead.model_validate(
            {**rows.get(session_id, {}), "session_id": session_id}
        )

    async def set_preferences(
        self, user_id: uuid.UUID, session_id: uuid.UUID | None, data: PushPreferencesUpdate
    ) -> PushPreferencesRead:
        if session_id is None or not await session_repo.update_push_preferences(
            self.db, user_id=user_id, session_id=session_id, patch=data.model_dump(mode="json")
        ):
            raise NotFoundError(message="This sign-in is no longer active.")
        return PushPreferencesRead.model_validate({**data.model_dump(), "session_id": session_id})

    async def focus(
        self, user_id: uuid.UUID, session_id: uuid.UUID | None, conversation_id: uuid.UUID | None
    ) -> None:
        if session_id is None or not await session_repo.update_push_preferences(
            self.db,
            user_id=user_id,
            session_id=session_id,
            patch={
                "focused_conversation": str(conversation_id) if conversation_id else None,
                "focus_until": (datetime.now(UTC) + timedelta(seconds=90)).isoformat()
                if conversation_id
                else None,
            },
        ):
            raise NotFoundError(message="This sign-in is no longer active.")
