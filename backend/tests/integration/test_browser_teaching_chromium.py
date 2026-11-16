"""Real PostgreSQL lifecycle and structural capture in one synthetic Chromium."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use._decision import Step
from app.agents.capabilities.browser_use._loop import BrowseSession, LoopPolicy, run_browse
from app.agents.capabilities.browser_use._page import StaleElement
from app.agents.capabilities.browser_use._teaching_page import TeachingPage
from app.agents.capabilities.skills._log import ServedSkill, SkillUseLog
from app.agents.spec import AgentSpec
from app.core.browser_teaching import ReviewedAction, TeachingParameter, TeachingReason
from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.skill import Skill
from app.db.models.skill_version import SkillVersion
from app.repositories import browser_teaching as repo
from app.repositories import skill_proposal as proposal_repo
from app.schemas.browser_teaching import TeachingChange, TeachingPropose
from app.schemas.resource_usage import ProposalDecision
from app.services.browser_teaching import (
    _capture,
    _discovery,
    _generation,
    _refinement,
    _refinement_capture,
)
from app.services.browser_teaching._capture import BrowserTeachingCapture
from app.services.browser_teaching._lease import TeachingIdentity
from app.services.skill_proposal import SkillProposalService
from tests.integration.test_browser_teaching import draft_runtime as draft_runtime
from tests.integration.test_browser_teaching import teaching as teaching
from tests.integration.test_browser_teaching_refinement import opt_in
from tests.test_browser_credential_chromium import ORIGIN, NativeDomain
from tests.test_browser_credential_chromium import browser as browser
from tests.test_browser_credential_chromium import chromium_process as chromium_process
from tests.test_browser_teaching_contracts import SECRET, review

pytestmark = [pytest.mark.anyio, pytest.mark.security]
FORM = """
<form onsubmit="return false">
<label for="record">Search</label><input id="record">
<label for="choice">Category</label><select id="choice"><option>First</option><option>Second</option></select>
<button id="search" type="button"><span id="inside">Find record</span></button>
</form>
"""


async def point(browser, selector):
    return await browser.evaluate(
        "(() => { const r = document.querySelector("
        + json.dumps(selector)
        + ").getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; })()"
    )


async def click(browser, x, y):
    for kind in ("mousePressed", "mouseReleased"):
        await browser.cdp.send(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            browser.session,
        )


@pytest.fixture
async def capture(browser, teaching, monkeypatch):
    t = teaching
    await browser.open(FORM, path="/items")
    browser.page._client.send.Input = NativeDomain(browser.cdp, "Input")
    await t.lease.close()
    native = TeachingPage(browser.page._credential_command)
    ident = TeachingIdentity.model_validate(
        t.held.model_dump(exclude={"takeover_id", "connection_id"})
    )

    @asynccontextmanager
    async def transaction():
        yield t.db
        await t.db.flush()

    monkeypatch.setattr(_capture, "get_db_context", transaction)
    monkeypatch.setattr(_refinement_capture, "get_db_context", transaction)
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 3600)
    recorder = BrowserTeachingCapture(
        context=t.ctx,
        identity=ident,
        redis=t.redis,
        page=native,
        guard=browser.page.output_guard,
        step=lambda: 1,
        locate=browser.page._locate,
    )
    events = []

    async def emit(event):
        events.append(recorder.event(event))
        return True

    try:
        yield recorder, events, emit
    finally:
        await recorder.close()


async def begin(t, recorder, emit):
    takeover = await recorder.begin(
        call_id=t.held.call_id,
        connection_id=t.held.connection_id,
        user_id=str(t.owner.id),
        emit=emit,
    )
    assert takeover is not None
    t.held = t.held.model_copy(update={"takeover_id": takeover})
    return await t.service.start(t.ctx, t.request(allowed_origins=(ORIGIN,)))


def command(t, sequence, kind, **values):
    return BrowserCommand(
        type=kind,
        by_user_id=str(t.owner.id),
        control_connection_id=t.held.connection_id,
        control_sequence=sequence,
        **values,
    )


async def test_real_manual_demonstration_becomes_only_an_explicitly_applied_skill(
    browser,
    teaching,
    capture,
    draft_runtime,
):
    t = teaching
    recorder, events, emit = capture
    started = await begin(t, recorder, emit)
    prepared = await recorder.before_input(
        command(t, 1, "navigate", url=ORIGIN + "/items?token=" + SECRET)
    )
    await browser.open(FORM, path="/items?token=" + SECRET)
    await recorder.after_input(prepared)
    x, y = await point(browser, "#record")
    prepared = await recorder.before_input(command(t, 2, "click", x=x, y=y))
    await click(browser, x, y)
    await recorder.after_input(prepared)
    prepared = await recorder.before_input(command(t, 3, "type", text=SECRET))
    await browser.cdp.send("Input.insertText", {"text": SECRET}, browser.session)
    await recorder.after_input(prepared)
    x, y = await point(browser, "#inside")
    prepared = await recorder.before_input(command(t, 4, "click", x=x, y=y))
    assert prepared.observation.target.role == "button"
    await click(browser, x, y)
    await recorder.after_input(prepared)
    stopped = await t.service.stop(t.ctx, started.id)
    assert [item.action for item in stopped.events] == [
        "navigate",
        "click",
        "input_parameter",
        "click",
    ]
    assert SECRET not in stopped.model_dump_json()
    assert all(SECRET not in event.model_dump_json() for event in events)
    assert await browser.evaluate("document.querySelector('#record').value") == SECRET
    chosen = review(
        ReviewedAction(sequence=1, label="Open the records page", path_template="/items"),
        ReviewedAction(sequence=2, label="Choose the search field"),
        ReviewedAction(sequence=3, label="Enter the requested record", parameter="record"),
        ReviewedAction(sequence=4, label="Find the requested record"),
        parameters=(TeachingParameter(name="record", description="The requested record"),),
    )
    reviewed = await t.service.change(
        t.ctx,
        started.id,
        stopped.revision,
        TeachingChange(action="review", review=chosen),
    )
    await recorder.end()
    await _generation.BrowserTeachingDraftService(t.db, t.redis).propose(
        t.ctx,
        started.id,
        reviewed.revision,
        TeachingPropose(),
    )
    await _generation.draft_browser_teaching(draft_runtime[0][-1][1])
    saved = await t.service.get(t.ctx, started.id)
    proposal = await proposal_repo.get(t.db, saved.proposal_id, organization_id=t.org.id)
    assert proposal.status == "pending" and proposal.skill_id is None
    assert SECRET not in proposal.content and SECRET not in str(proposal.browser_procedure)
    await SkillProposalService(t.db).apply(
        t.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
    )
    skill = await t.db.scalar(
        select(Skill).where(Skill.organization_id == t.org.id, Skill.name == proposal.name)
    )
    version = await t.db.get(SkillVersion, skill.latest_version_id)
    assert version.browser_procedure == proposal.browser_procedure
    assert (await repo.session(t.db, t.org.id, started.id)).sanitized_events == []

    spec = AgentSpec.model_validate(t.version.spec).model_copy(update={"skill_ids": [skill.id]})
    published = AgentVersion(
        organization_id=t.org.id, agent_id=t.agent.id, version=2, spec=spec.model_dump(mode="json")
    )
    t.db.add(published)
    await t.db.flush()
    t.agent.current_version_id = published.id
    t.run.status = RunStatus.COMPLETED.value
    later = AgentRun(
        organization_id=t.org.id,
        user_id=t.owner.id,
        agent_id=t.agent.id,
        agent_version_id=published.id,
        conversation_id=t.run.conversation_id,
        status=RunStatus.RUNNING.value,
        surface=RunSurface.WEB.value,
    )
    t.db.add(later)
    await t.db.flush()
    t.run = later
    log = SkillUseLog(agent_id=t.agent.id, served={skill.name: ServedSkill(skill.id, version.id)})
    found = await _discovery.discover(t.db, t.deps(), log, ORIGIN)
    assert len(found) == 1 and found[0].skill_version_id == version.id
    await browser.open(FORM, path="/items")
    snapshot = await browser.snapshot()
    field = next(item for item in snapshot.elements if item.path == "#record")
    await browser.page.type_text(field, "fresh reviewed parameter")
    assert (
        await browser.evaluate("document.querySelector('#record').value")
        == "fresh reviewed parameter"
    )
    await browser.evaluate(
        "document.querySelector('#record').outerHTML = '<button id=\"record\">Changed control</button>'"
    )
    with pytest.raises(StaleElement):
        await browser.page.type_text(field, SECRET)
    assert (
        await browser.evaluate("document.querySelector('#record').textContent") == "Changed control"
    )


@pytest.mark.parametrize(
    "body",
    [
        '<form><input id="field"><input type="password"></form>',
        '<input id="field" autocomplete="one-time-code">',
        '<div data-sitekey="synthetic"><button id="field">Synthetic CAPTCHA</button></div>',
        '<iframe id="field"></iframe>',
        '<form><input id="field">' + "<input>" * 501 + "</form>",
    ],
)
async def test_authentication_and_unbounded_forms_become_value_free_human_checkpoints(
    browser, teaching, capture, body
):
    t = teaching
    recorder, events, emit = capture
    started = await begin(t, recorder, emit)
    await browser.open(body, path="/auth")
    x, y = await point(browser, "#field")
    prepared = await recorder.before_input(command(t, 1, "click", x=x, y=y))
    assert prepared.observation.human_required and prepared.observation.target is None
    await click(browser, x, y)
    await recorder.after_input(prepared)
    data = await t.service.get(t.ctx, started.id)
    assert data.status == "paused" and data.reason_code == TeachingReason.AUTHENTICATION
    assert data.events[0].human_step and data.events[0].target is None
    assert SECRET not in data.model_dump_json()


async def test_native_combobox_choice_is_a_reviewed_parameter_and_never_an_option_value(
    browser, teaching, capture
):
    t = teaching
    recorder, _, emit = capture
    started = await begin(t, recorder, emit)
    await browser.evaluate("document.querySelector('#choice').focus()")
    prepared = await recorder.before_input(command(t, 1, "key", key="ArrowDown"))
    await browser.cdp.send(
        "Input.dispatchKeyEvent",
        {"type": "keyDown", "key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
        browser.session,
    )
    await browser.cdp.send(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
        browser.session,
    )
    await recorder.after_input(prepared)
    data = await t.service.get(t.ctx, started.id)
    assert data.events[0].action == "select" and data.events[0].target.role == "combobox"
    assert "Second" not in data.model_dump_json() and "ArrowDown" not in data.model_dump_json()


async def test_protected_delivery_ends_teaching_and_late_events_cannot_restore_page_output(
    browser, teaching, capture
):
    t = teaching
    recorder, _, emit = capture
    started = await begin(t, recorder, emit)
    await recorder.protect()
    browser.page.protect_credentials(ORIGIN)
    await browser.evaluate("document.querySelector('#record').focus()")
    await browser.cdp.send("Input.insertText", {"text": SECRET}, browser.session)
    assert await recorder.before_input(command(t, 1, "type", text=SECRET)) is None
    await recorder.after_input(None)
    data = await t.service.get(t.ctx, started.id)
    assert data.status == "paused" and data.reason_code == TeachingReason.PROTECTED
    assert data.events == ()
    late = browser.page.output_guard.event(
        recorder.event(
            BrowserEvent(
                kind="browser_frame",
                call_id=t.held.call_id,
                step=2,
                image=SECRET,
                title=SECRET,
                detail=SECRET,
                url=ORIGIN + "/?token=" + SECRET,
            )
        )
    )
    assert late.output_protected and SECRET not in late.model_dump_json()
    assert SECRET not in (await browser.snapshot()).text


async def test_native_successful_task_waits_for_actual_run_completion_without_a_paid_model(
    browser, teaching, capture
):
    t = teaching
    recorder, events, emit = capture
    await opt_in(t)
    steps = iter(
        [
            Step(
                evaluation="Start",
                memory="",
                next_goal="Fill the field",
                action={"action": "type", "index": 0, "text": SECRET},
            ),
            Step(
                evaluation="The synthetic task finished",
                memory="",
                next_goal="Finish",
                action={"action": "done", "answer": "Finished"},
            ),
        ]
    )
    decide = AsyncMock(side_effect=lambda *_: next(steps))
    result = await run_browse(
        task="Fill the synthetic field",
        session=BrowseSession(page=browser.page, tab_id="main", teaching=recorder),
        decide=decide,
        policy=LoopPolicy(max_steps=3, preview=False),
        call_id="native-refinement",
        sink=emit,
        run_id=str(t.run.id),
    )
    assert result.outcome == "done"
    event = next(item for item in reversed(events) if item.teaching_session_id is not None)
    row = await repo.session(t.db, t.org.id, event.teaching_session_id)
    assert row.status == "review" and row.browser_completed and not row.verified_success
    assert SECRET not in str(row.sanitized_events)
    assert all(SECRET not in item.model_dump_json() for item in events)
    t.run.status = RunStatus.COMPLETED.value
    await t.db.flush()
    await _refinement.reconcile(t.db, row)
    assert row.verified_success
