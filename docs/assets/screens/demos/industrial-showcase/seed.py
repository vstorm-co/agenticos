"""Publish private, fictional industrial Apps and a prepared sales Visuals chat.

Use an isolated demonstration database and its existing owner. No models, provider
credentials, ERP systems or equipment are used by this seed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.agents.capabilities.visuals._toolset import content_problem
from app.core.permissions import AuthContext
from app.db.models.artifact import ArtifactMediaType
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.session import get_db_context
from app.repositories import conversation as conversations
from app.repositories import visual as visuals
from app.schemas.visual import VisualPublish
from app.services.artifact import publish_problem, publish_with
from app.services.visual import VisualService
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demo_agents import BOOTSTRAP, ORGANIZATION, ensure_agent  # noqa: E402


@dataclass(frozen=True, slots=True)
class SeedOptions:
    org: UUID
    user: UUID
    output: Path


async def seed(args: SeedOptions) -> None:
    source = Path(__file__).resolve().parent.parent
    async with get_db_context() as db:
        owner = await db.get(User, args.user)
        organization = await db.get(Organization, args.org)
        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == args.org,
                OrganizationMember.user_id == args.user,
            )
        )
        if organization is None or organization.name != ORGANIZATION:
            raise ValueError(
                f"This seed only supports the isolated {ORGANIZATION} demonstration - "
                f"create it with `{BOOTSTRAP}`"
            )
        if owner is None or member is None or member.role != "owner":
            raise ValueError("Choose the existing demo organization owner")
        ctx = AuthContext(
            user_id=args.user,
            organization_id=args.org,
            role=member.role,
            is_app_admin=owner.is_app_admin,
        )
        agent = await ensure_agent(db, ctx, "Visuals Lab", model_profile_id=None)
        apps: dict[str, str] = {}
        for name, title in [
            ("northline-operations", "Northline · Supply & Production"),
            ("motor-atlas", "Motor Atlas · Assembly explorer"),
        ]:
            data = (source / f"{name}.html").read_bytes()
            problem = publish_problem(
                name=f"demo-{name}", media_type=ArtifactMediaType.HTML, data=data
            )
            if problem:
                raise ValueError(problem)
            published = await publish_with(
                db,
                organization_id=args.org,
                agent_id=agent.id,
                owner_user_id=args.user,
                run_id=None,
                name=f"demo-{name}",
                title=title,
                media_type=ArtifactMediaType.HTML,
                data=data,
            )
            apps[name] = str(published.artifact_id)
        title = "Revenue Pulse — six-month sales review"
        thread = await db.scalar(
            select(Conversation).where(
                Conversation.organization_id == args.org,
                Conversation.user_id == args.user,
                Conversation.title == title,
            )
        )
        if thread is None:
            thread = await conversations.create_conversation(
                db, organization_id=args.org, user_id=args.user, title=title
            )
            await conversations.create_message(
                db,
                conversation_id=thread.id,
                role="user",
                author_user_id=args.user,
                content="Turn our demo sales rows into an interactive review: revenue vs target, pipeline and team contribution. Keep region and period filters, then save it to Apps.",
            )
            message = await conversations.create_message(
                db,
                conversation_id=thread.id,
                role="assistant",
                agent_id=agent.id,
                content="Revenue Pulse is ready to inspect. Change the region or period, compare revenue with the target and open a teammate's contribution.\n\nPrepared Visuals demonstration with fictional sales data; no live CRM or model-generation run is represented.",
            )
            draw = await conversations.create_tool_call(
                db,
                message_id=message.id,
                tool_call_id="demo-revenue-pulse",
                tool_name="draw",
                args={},
                started_at=datetime.now(UTC),
            )
            await conversations.complete_tool_call(
                db,
                db_tool_call=draw,
                result="Drew Revenue Pulse as visual `demo-revenue-pulse`. Prepared fixture; no model was called.",
                completed_at=datetime.now(UTC),
                success=True,
            )
            draw.duration_ms = None
            await visuals.record(
                db,
                organization_id=args.org,
                conversation_id=thread.id,
                tool_call_id=draw.tool_call_id,
                agent_id=agent.id,
                user_id=args.user,
                title="Revenue Pulse · Sales performance",
                kind="html",
                revision_of=None,
            )
        draw = await db.scalar(
            select(ToolCall).where(
                ToolCall.tool_call_id == "demo-revenue-pulse",
                ToolCall.message_id.in_(
                    select(Message.id).where(Message.conversation_id == thread.id)
                ),
            )
        )
        if draw is None:
            raise ValueError("The prepared revenue visual is missing")
        message = await db.get(Message, draw.message_id)
        if message is None or message.run_id is not None:
            raise ValueError("The fixture cannot overwrite a model-generated message")
        html = (source / "revenue-pulse.html").read_text()
        problem = content_problem("html", html)
        if problem:
            raise ValueError(problem)
        draw.result = "Drew Revenue Pulse as visual `demo-revenue-pulse`. Prepared fixture; no model was called."
        draw.args = {
            "title": "Revenue Pulse · Sales performance",
            "kind": "html",
            "height": 630,
            "content": html,
        }
        await db.commit()
        published = await VisualService(db).publish(
            ctx,
            thread.id,
            draw.tool_call_id,
            VisualPublish(
                name="demo-revenue-pulse", title="Revenue Pulse · Sales performance"
            ),
        )
        apps["revenue-pulse"] = str(published.artifact_id)
        await db.commit()
        args.output.write_text(
            json.dumps(
                {
                    "organization": str(args.org),
                    "conversation": str(thread.id),
                    "apps": apps,
                    "scope": "Prepared fictional Apps and conversation. No model, ERP, CRM or equipment connection.",
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "Published three private Apps and one prepared sales Visuals conversation."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", type=UUID, required=True)
    parser.add_argument("--user", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-demo", action="store_true", required=True)
    parsed = parser.parse_args()
    if (
        not isinstance(parsed.org, UUID)
        or not isinstance(parsed.user, UUID)
        or not isinstance(parsed.output, Path)
    ):
        raise TypeError("The demo arguments must contain UUIDs and an output path")
    asyncio.run(
        seed(SeedOptions(org=parsed.org, user=parsed.user, output=parsed.output))
    )
