"""The virtual terminal (#2191): what may be mounted, and what a person approves.

Runs the real library over in-memory folders. The parts worth a test are the
refusals - a backend this deployment cannot run, a credential in the wrong place,
an endpoint an author must not reach, a write into a folder whose author asked to
be asked - and the one mechanism that is easy to get wrong: the question is put
before the call runs, because Mirage swallows an exception raised from inside it.
"""

import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, ApprovalRequired
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from app.agents.approval import ApprovalGranted, ApprovalPending, ApprovalRejected, ApprovalRequest
from app.agents.capabilities._registry import CapabilityBinding, build, load_builtins
from app.agents.capabilities.mirage import (
    MIRAGE_CAPABILITY_ID,
    MIRAGE_MOUNTS_RESOURCE,
    MirageConfig,
    MirageMount,
    ResolvedMount,
    ResolvedTerminal,
    _backends,
    _policy,
    backend,
    catalog,
)
from app.agents.capabilities.mirage._capability import Mirage, instructions
from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]


def _ram(path: str, *, mode: str = "write", approve: bool = False) -> ResolvedMount:
    return ResolvedMount(path, "ram", mode, approve, {}, path.strip("/"))  # ty: ignore[invalid-argument-type]


def _mount(**fields: Any) -> MirageMount:
    return MirageMount.model_validate({"path": "/f/", "backend": "ram", **fields})


# -- the catalog ---------------------------------------------------------------


def test_the_extra_and_the_suite_pin_the_same_mirage() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extra = project["project"]["optional-dependencies"]["mirage"]
    dev = [dep for dep in project["dependency-groups"]["dev"] if str(dep).startswith("mirage-ai")]
    assert dev == extra


def test_a_saas_backend_offers_its_options_and_asks_the_vault_for_its_token() -> None:
    github = backend("github")
    assert github is not None and github.available and github.credential == "fields"
    assert github.secret_fields == ("token",) and github.required_secrets == ("token",)
    # The endpoint override is not something an author may point elsewhere.
    assert "base_url" not in github.options_schema["properties"]
    assert set(github.options_schema["properties"]) == {"owner", "repo", "ref"}


def test_a_google_backend_signs_in_with_an_account_not_with_fields() -> None:
    drive = backend("gdrive")
    assert drive is not None and drive.credential == "google"
    assert drive.secret_fields == ()
    assert not {"access_token", "client_id", "client_secret", "refresh_token", "api_base"} & set(
        drive.options_schema["properties"]
    )


def test_microsoft_backends_take_an_entra_app_and_dify_keeps_its_address() -> None:
    onedrive = backend("onedrive")
    dify = backend("dify")
    assert onedrive is not None and onedrive.credential == "microsoft"
    assert "access_token" not in onedrive.options_schema["properties"]
    assert dify is not None and "base_url" in dify.options_schema["properties"]
    assert dify.address_fields == ("base_url",)


def test_ssh_hides_the_hosts_own_files_and_redis_is_typed_here() -> None:
    ssh = backend("ssh")
    redis = backend("redis")
    assert ssh is not None and not {"identity_file", "known_hosts"} & set(
        ssh.options_schema["properties"]
    )
    assert ssh.secret_fields == ("password", "passphrase")
    assert redis is not None and redis.secret_fields == ("url",)


def test_a_backend_this_deployment_cannot_run_says_why() -> None:
    s3 = backend("s3")
    disk = backend("disk")
    assert s3 is not None and not s3.available and "aioboto3" in (s3.reason or "")
    assert disk is not None and not disk.available
    assert [info.available for info in catalog()] == sorted(
        (info.available for info in catalog()), reverse=True
    )
    assert backend("nobody") is None


def test_scratch_takes_no_config_and_a_missing_library_is_unavailable(monkeypatch) -> None:
    ram = backend("ram")
    assert ram is not None and ram.credential == "none" and ram.options_schema == {}

    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(_backends, "config_class", missing)
    assert _backends._describe("github").reason == "Its library is not installed."


def test_config_class_refuses_what_it_cannot_build(monkeypatch) -> None:
    with pytest.raises(ImportError):
        _backends.config_class("s3")
    from mirage.vfs import registry

    monkeypatch.setitem(
        registry.REGISTRY, "plain", registry.VFSEntry("mirage.vfs.ram:RAMVFS", object)
    )
    with pytest.raises(TypeError):
        _backends.config_class("plain")


def test_without_mirage_the_catalog_is_empty_and_says_so(monkeypatch) -> None:
    import sys

    _backends.catalog.cache_clear()
    monkeypatch.setitem(sys.modules, "mirage.vfs.registry", None)
    try:
        assert catalog() == ()
        with pytest.raises(ValidationError, match="does not have the virtual terminal installed"):
            _mount()
    finally:
        monkeypatch.undo()
        _backends.catalog.cache_clear()


def test_a_secret_hidden_in_an_any_of_is_still_a_secret() -> None:
    assert _backends._is_secret(
        {"anyOf": [{"type": "string", "format": "password"}, {"type": "null"}]}
    )
    assert not _backends._is_secret({"type": "string"})


# -- the config ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"path": "drive"}, "one lowercase name between slashes"),
        ({"backend": "nobody"}, "not a service the terminal can mount"),
        ({"backend": "s3"}, "cannot be mounted here"),
        ({"options": {"colour": "blue"}}, "has no setting colour"),
        ({"backend": "github"}, "needs a secret for token"),
        (
            {"backend": "github", "secrets": {"password": "00000000-0000-0000-0000-000000000001"}},
            "has no credential password",
        ),
        (
            {"backend": "github", "account": {"kind": "personal"}},
            "does not sign in with an account",
        ),
        ({"backend": "gdrive"}, "needs an account"),
        (
            {
                "backend": "gdrive",
                "account": {"kind": "personal"},
                "secrets": {"token": "00000000-0000-0000-0000-000000000001"},
            },
            "signs in with an account, not with secrets",
        ),
        ({"backend": "onedrive"}, "needs the Entra app"),
        (
            {
                "backend": "github",
                "secrets": {"token": "00000000-0000-0000-0000-000000000001"},
                "options": {"owner": "o", "repo": 7},
            },
            "repo",
        ),
        (
            {"backend": "github", "secrets": {"token": "00000000-0000-0000-0000-000000000001"}},
            "requires owner and repo",
        ),
    ],
)
def test_a_mount_that_does_not_fit_its_backend_is_refused(fields, message) -> None:
    with pytest.raises(ValidationError, match=message):
        _mount(**fields)


def test_mounts_that_fit_their_backends_validate() -> None:
    secret = "00000000-0000-0000-0000-000000000001"
    config = MirageConfig.model_validate(
        {
            "mounts": [
                {
                    "path": "/code/",
                    "backend": "github",
                    "secrets": {"token": secret},
                    "options": {"owner": "o", "repo": "r"},
                },
                {
                    "path": "/drive/",
                    "backend": "gdrive",
                    "account": {"kind": "organization", "connection_id": secret},
                },
                {"path": "/files/", "backend": "sharepoint", "secrets": {"app": secret}},
            ],
            "allowed_commands": ["ls", "grep"],
            "hidden_paths": ["/drive/HR/"],
        }
    )
    assert [mount.backend for mount in config.mounts] == ["github", "gdrive", "sharepoint"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            {"mounts": [{"path": "/a/", "backend": "ram"}, {"path": "/a/", "backend": "ram"}]},
            "share a name",
        ),
        (
            {"mounts": [{"path": "/a/", "backend": "ram"}], "allowed_commands": ["rm -rf"]},
            "not a command name",
        ),
        (
            {"mounts": [{"path": "/a/", "backend": "ram"}], "hidden_paths": ["HR"]},
            "not an absolute path",
        ),
        ({"mounts": []}, "at least 1"),
    ],
)
def test_a_terminal_config_that_cannot_be_one_is_refused(config, message) -> None:
    with pytest.raises(ValidationError, match=message):
        MirageConfig.model_validate(config)


# -- building --------------------------------------------------------------------


def test_without_resolved_folders_the_capability_contributes_nothing() -> None:
    load_builtins()
    binding = CapabilityBinding(
        capability_id=MIRAGE_CAPABILITY_ID, config={"mounts": [{"path": "/a/", "backend": "ram"}]}
    )
    assert build([binding]) == []
    assert build([binding], resources={MIRAGE_MOUNTS_RESOURCE: ResolvedTerminal(mounts=())}) == []
    assert build([binding], resources={MIRAGE_MOUNTS_RESOURCE: object()}) == []


def test_the_folders_and_the_policy_reach_the_terminal() -> None:
    load_builtins()
    terminal = ResolvedTerminal(mounts=(_ram("/a/"),), notes=("/b/ is not mounted: gone.",))
    [built] = build(
        [
            CapabilityBinding(
                capability_id=MIRAGE_CAPABILITY_ID,
                config={"mounts": [{"path": "/a/", "backend": "ram"}], "allowed_commands": ["ls"]},
            )
        ],
        resources={MIRAGE_MOUNTS_RESOURCE: terminal},
    )
    assert isinstance(built, Mirage)
    assert built.allowed_commands == ("ls",) and built.notes == terminal.notes
    assert "/b/ is not mounted" in built.get_instructions()


def test_instructions_say_what_each_folder_allows() -> None:
    text = instructions(
        (_ram("/ro/", mode="read"), _ram("/ask/", approve=True), _ram("/free/")), ("x",)
    )
    assert "/ro/: ro (read-only)" in text
    assert "/ask/: ask (writable; a person approves each write" in text
    assert "/free/: free (writable)" in text


def test_a_resolved_mount_keeps_its_credentials_out_of_its_repr() -> None:
    from pydantic import SecretStr

    mount = ResolvedMount(
        "/code/",
        "github",
        "read",
        False,
        {"token": SecretStr("s3cret"), "owner": "o", "repo": "r"},
        "code",
    )
    assert "s3cret" not in repr(mount) and "repo" not in repr(mount)
    assert mount.build().vfs is not None


# -- running -------------------------------------------------------------------


def _calls(*calls: tuple[str, dict[str, Any]]):
    """A model that makes these calls in turn, then reports every tool result."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [
            part
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, ToolReturnPart)
        ]
        if len(returns) < len(calls):
            name, args = calls[len(returns)]
            return ModelResponse(parts=[ToolCallPart(name, args, tool_call_id=f"c{len(returns)}")])
        return ModelResponse(parts=[TextPart("\n".join(str(part.content) for part in returns))])

    return respond


def _agent(terminal: Mirage, model) -> Agent[AgentDeps, str | DeferredToolRequests]:
    return Agent(
        FunctionModel(model),
        deps_type=AgentDeps,
        capabilities=[terminal],
        output_type=[str, DeferredToolRequests],
    )


def _gate(answer):
    asked: list[ApprovalRequest] = []

    async def request(req: ApprovalRequest):
        asked.append(req)
        return answer(req)

    return request, asked


async def test_the_tools_reach_the_terminal_and_a_read_only_folder_refuses_a_write() -> None:
    terminal = Mirage(mounts=(_ram("/ro/", mode="read"), _ram("/free/")))
    run = await _agent(
        terminal,
        _calls(
            ("mirage_execute", {"command": "echo hi > /free/a.txt && cat /free/a.txt"}),
            ("mirage_write_file", {"path": "/ro/b.txt", "content": "x"}),
        ),
    ).run("go", deps=AgentDeps())
    assert "hi" in run.output
    assert "Read-only" in run.output or "read-only" in run.output.lower()


async def test_a_write_to_an_approved_folder_parks_until_a_person_answers() -> None:
    request, asked = _gate(lambda req: ApprovalPending())
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    agent = _agent(
        terminal, _calls(("mirage_execute", {"command": "echo hi > /ask/a.txt && cat /ask/a.txt"}))
    )

    parked = await agent.run("go", deps=AgentDeps(request_approval=request))
    assert isinstance(parked.output, DeferredToolRequests)
    assert asked[0].capability_id == "mirage" and asked[0].tool_name == "mirage_execute"

    granted, _ = _gate(lambda req: ApprovalGranted(tool_args=req.tool_args))
    resumed = await agent.run(
        message_history=parked.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={"c0": True}),
        deps=AgentDeps(request_approval=granted),
    )
    assert "hi" in resumed.output


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (ApprovalRejected(note="not today"), "not today"),
        (ApprovalRejected(), "a reviewer rejected it"),
        (
            ApprovalGranted(tool_args={"path": "/ask/other.txt", "content": "x"}),
            "different arguments",
        ),
    ],
)
async def test_a_refused_or_altered_approval_writes_nothing(answer, said) -> None:
    request, _ = _gate(lambda req: answer)
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    run = await _agent(
        terminal,
        _calls(
            ("mirage_write_file", {"path": "/ask/a.txt", "content": "x"}),
            ("mirage_ls", {"path": "/ask"}),
        ),
    ).run("go", deps=AgentDeps(request_approval=request))
    assert said in run.output
    assert "a.txt" not in run.output.split("\n", 1)[-1]


async def test_an_approved_file_write_reaches_the_folder() -> None:
    """The file tools write through Mirage's own file calls, which ask too."""
    request, asked = _gate(lambda req: ApprovalGranted(tool_args=req.tool_args))
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    run = await _agent(
        terminal,
        _calls(
            ("mirage_write_file", {"path": "/ask/a.txt", "content": "written"}),
            ("mirage_read_file", {"path": "/ask/a.txt"}),
        ),
    ).run("go", deps=AgentDeps(request_approval=request))
    assert len(asked) == 1 and "written" in run.output


async def test_with_nobody_to_ask_a_gated_write_is_refused() -> None:
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    run = await _agent(
        terminal,
        _calls(("mirage_edit_file", {"path": "/ask/a.txt", "old_string": "a", "new_string": "b"})),
    ).run("go", deps=AgentDeps())
    assert "cannot ask anyone" in run.output


async def test_a_write_no_dry_run_could_see_is_refused_rather_than_unasked() -> None:
    """`$TARGET` is expanded only as the line runs, so `explain` sees no write;
    the backstop refuses it instead of letting it through unapproved."""
    request, asked = _gate(lambda req: ApprovalGranted(tool_args=req.tool_args))
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    run = await _agent(
        terminal,
        _calls(("mirage_execute", {"command": "T=/ask/x.txt; echo hi > $T; cat /ask/x.txt"})),
    ).run("go", deps=AgentDeps(request_approval=request))
    assert asked == []
    assert "hi" not in run.output


async def test_reads_and_unapproved_folders_ask_nobody() -> None:
    request, asked = _gate(lambda req: ApprovalPending())
    terminal = Mirage(mounts=(_ram("/ask/", approve=True), _ram("/free/")))
    run = await _agent(
        terminal,
        _calls(
            ("mirage_ls", {"path": "/ask"}),
            ("mirage_write_file", {"path": "/free/a.txt", "content": "x"}),
        ),
    ).run("go", deps=AgentDeps(request_approval=request))
    assert asked == [] and isinstance(run.output, str)


async def test_the_command_allowlist_and_hidden_paths_hold_in_the_shell() -> None:
    terminal = Mirage(
        mounts=(_ram("/a/"),), allowed_commands=("ls", "echo"), hidden_paths=("/a/secret/",)
    )
    run = await _agent(
        terminal,
        _calls(
            ("mirage_execute", {"command": "echo x > /a/visible.txt && ls /a"}),
            ("mirage_execute", {"command": "cat /a/visible.txt"}),
        ),
    ).run("go", deps=AgentDeps())
    first, second = run.output.split("\n", 1)[0], run.output
    assert "visible.txt" in first
    assert "cat" in second and ("not" in second.lower() or "denied" in second.lower())


async def test_the_terminal_is_closed_when_the_run_ends() -> None:
    terminal = Mirage(mounts=(_ram("/a/"),))
    agent = _agent(terminal, _calls(("mirage_ls", {"path": "/a"})))
    await agent.run("go", deps=AgentDeps())
    # A fresh instance per run: the original never opened one.
    assert terminal._workspace is None
    workspace = await terminal.workspace()
    assert await terminal.workspace() is workspace

    async def finish() -> Any:
        return "done"

    await terminal.wrap_run(SimpleNamespace(), handler=finish)  # ty: ignore[invalid-argument-type]
    assert terminal._workspace is None
    await terminal.wrap_run(SimpleNamespace(), handler=finish)  # ty: ignore[invalid-argument-type]


# -- the policy, directly ------------------------------------------------------


async def test_needs_approval_reads_the_call_it_is_given() -> None:
    terminal = Mirage(mounts=(_ram("/ask/", approve=True),))
    workspace = await terminal.workspace()
    gated = terminal.gated
    assert not await _policy.needs_approval(
        workspace, frozenset(), "write_file", {"path": "/ask/a"}
    )
    assert await _policy.needs_approval(workspace, gated, "write_file", {"path": "ask/a"})
    assert not await _policy.needs_approval(workspace, gated, "edit_file", {"path": "/elsewhere"})
    assert await _policy.needs_approval(
        workspace, gated, "execute", {"command": "cp /ask/a /ask/b"}
    )
    assert not await _policy.needs_approval(workspace, gated, "execute", {"command": "ls /ask"})
    assert not await _policy.needs_approval(workspace, gated, "ls", {"path": "/ask"})
    await workspace.close()


def test_an_ask_at_the_top_of_a_line_counts() -> None:
    from mirage import Ask

    top = SimpleNamespace(answers=(Ask(reason="r"),), node=SimpleNamespace(children=()))
    none = SimpleNamespace(answers=(), node=SimpleNamespace(answers=(), children=()))
    assert _policy._asks(top)  # ty: ignore[invalid-argument-type]
    assert not _policy._asks(none)  # ty: ignore[invalid-argument-type]


async def test_the_backstop_allows_only_inside_an_approved_call() -> None:
    from mirage.policy.types import Decision, Outcome

    decision = Decision(
        id="d",
        session_id="s",
        command="echo",
        argv=(),
        cwd="/",
        paths=(),
        reason="r",
        rule=None,  # ty: ignore[invalid-argument-type]
    )
    assert (await _policy.ask(decision)).outcome is Outcome.DENY
    with _policy.approved_writes(True):
        assert (await _policy.ask(decision)).outcome is Outcome.ALLOW


async def test_a_pending_answer_parks_from_outside_the_library() -> None:
    async def pending(request: ApprovalRequest):
        return ApprovalPending()

    ctx = SimpleNamespace(deps=SimpleNamespace(request_approval=pending), tool_call_id=None)
    with pytest.raises(ApprovalRequired):
        await _policy.approve(ctx, "mirage_execute", {"command": "x"})  # ty: ignore[invalid-argument-type]
