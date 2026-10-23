"""The morning briefing: what a person's watches found that could wait (#2301).

A finding nobody asked to hear at once waits for the person's morning - the
organization's days and hour, or an hour before their working hours, as the
nightly look keeps them. Then one notification says how many are new and one
direct message from each chat-app bot that knows them lists them. Each finding
goes out in one briefing only, so a second sweep the same morning says nothing.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import member_repo, suggestion_repo, user_repo
from app.services.notifications import NotificationService
from app.services.proactive._welcome import direct_message

LISTED = 5
"""How many a direct message names before it says how many more."""

HEADING = {
    "en": "{count} new from your watches:",
    "pl": "Znaleziska z twoich obserwacji ({count}):",
    "de": "Neu aus Ihren Beobachtungen ({count}):",
}
MORE = {"en": "…and {count} more.", "pl": "…i jeszcze {count}.", "de": "…und {count} weitere."}
OPEN = {
    "en": "All of it in your inbox: {url}",
    "pl": "Wszystko w twoim inboksie: {url}",
    "de": "Alles in Ihrem Posteingang: {url}",
}


def _message(locale: str | None, titles: list[str], url: str) -> str:
    language = locale if locale in HEADING else "en"
    lines = [HEADING[language].replace("{count}", str(len(titles)))]
    lines += [f"• {title}" for title in titles[:LISTED]]
    if len(titles) > LISTED:
        lines.append(MORE[language].replace("{count}", str(len(titles) - LISTED)))
    lines.append(OPEN[language].replace("{url}", url))
    return "\n".join(lines)


async def brief(db: AsyncSession, organization_id: UUID, user_id: UUID, *, now: datetime) -> int:
    """Send one person their briefing, if anything waits. Returns how many findings it listed."""
    user = await user_repo.get_by_id(db, user_id)
    if user is None or not user.is_active:
        return 0
    if await member_repo.get_active(db, organization_id=organization_id, user_id=user_id) is None:
        return 0
    findings = await suggestion_repo.unbriefed_findings(
        db, organization_id=organization_id, user_id=user_id
    )
    if not findings:
        return 0
    await NotificationService(db).briefing(
        organization_id=organization_id, user_id=user_id, count=len(findings), now=now
    )
    text = _message(
        user.locale, [finding.title for finding in findings], f"{settings.FRONTEND_URL}/inbox"
    )
    await direct_message(db, organization_id, user.email, lambda _bot: text)
    await suggestion_repo.mark_briefed(
        db, suggestion_ids=[finding.id for finding in findings], at=now
    )
    return len(findings)
