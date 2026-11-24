#!/usr/bin/env python3
"""Install the checked-in accounting pack as drafts through the t3OS public API.

Contract: docs/api.md, app/api/routes/v1/{permissions,skills,agents,model_providers}.py,
and AgentSpec version 14. This is a create-only installer, not an upgrade tool.
"""

import argparse
import copy
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

import yaml

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
type JsonObject = dict[str, Json]

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("manifest.json")
KEY_PATTERN = re.compile(r"finance/[a-z0-9]+(?:-[a-z0-9]+)*\Z")
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MAX_RESOURCE_BYTES = 512 * 1024
TAGS = ["accounting-firm"]

# These are the explicit defaults in app/agents/spec.py, not a permissive filter.
# Comparing the complete spec also catches edits to fields the pack does not set.
# Verified against its real Pydantic serialization; see INSTALL.md for source hashes.
SPEC_DEFAULTS: JsonObject = {
    "spec_version": 14,
    "variables": [],
    "starters": [],
    "starter_titles": {},
    "starter_icons": {},
    "time_zone": "system",
    "model_settings": {},
    "table_bindings": [],
    "collection_ids": [],
    "context_ids": [],
    "mcp_servers": [],
    "subagents": [],
    "external_agents": [],
    "max_steps": None,
    "output_schema": None,
    "loop_guard": {"enabled": True, "repeats": 4, "cycles": 3},
    "reviewers": [],
    "code_mode": {"enabled": False, "max_tool_calls": 100},
    "budget": None,
    "notifications": {
        "budget": {"enabled": True, "to": ["admins", "owner"], "user_ids": []},
        "approvals": {"enabled": True, "to": ["initiator", "admins"], "user_ids": []},
        "usage": {"enabled": False, "to": ["admins", "owner"], "user_ids": []},
    },
    "observability": None,
    "speech_to_text": None,
    "voice": None,
}
CAPABILITY_DEFAULTS: JsonObject = {
    "config": {},
    "approval": "default",
    "tool_approval": {},
    "tool_overrides": {},
    "secret_id": None,
    "enabled": True,
}


class InstallError(Exception):
    """A refusal that leaves existing content intact."""

    def __init__(self, message: str, *, details: JsonObject | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


def object_value(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InstallError(f"{label} must be an object")
    # JSON round-tripping also rejects YAML-only objects such as timestamps.
    try:
        result: JsonObject = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InstallError(f"{label} must contain JSON-compatible values") from exc
    return result


def text_value(value: Json, label: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"{label} must be a nonempty string")
    value = value.strip()
    if maximum is not None and len(value) > maximum:
        raise InstallError(f"{label} exceeds {maximum} characters")
    return value


def strings(value: Json, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InstallError(f"{label} must be a list of strings")
    return [text_value(item, label) for item in value]


def uuid_value(value: Json, label: str) -> str:
    try:
        return str(UUID(text_value(value, label)))
    except (ValueError, AttributeError) as exc:
        raise InstallError(f"{label} must be a UUID") from exc


def unique(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise InstallError(f"{label} contains duplicates")


def frontmatter(path: Path) -> tuple[JsonObject, str]:
    try:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        if not lines or lines[0] != "---":
            raise InstallError(f"{path} needs YAML frontmatter")
        end = lines.index("---", 1)
        metadata = object_value(yaml.safe_load("\n".join(lines[1:end])), str(path))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise InstallError(f"Cannot read manifest {path}") from exc
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise InstallError(f"{path} has no instruction body")
    return metadata, body


def catalog_folder(root: Path, catalog: str, key: str) -> Path:
    if not KEY_PATTERN.fullmatch(key):
        raise InstallError(f"Unsupported catalog key: {key}")
    base = root / "backend/app/core/catalog" / catalog
    folder = base / key
    if not folder.is_dir() or not folder.resolve().is_relative_to(base.resolve()):
        raise InstallError(f"Catalog folder is missing or escapes its root: {key}")
    if any(part.is_symlink() for part in [folder, *folder.parents] if part != root.parent):
        raise InstallError(f"Catalog symlinks are not supported: {key}")
    return folder


@dataclass(frozen=True)
class Resource:
    name: str
    content: str

    def payload(self) -> JsonObject:
        return {"name": self.name, "description": None, "content": self.content}


@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    description: str
    content: str
    category: str
    resources: tuple[Resource, ...]

    def payload(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "category": self.category,
            "visibility": "org",
        }


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    description: str
    instructions: str
    capabilities: tuple[JsonObject, ...]
    skills: tuple[str, ...]
    starters: tuple[str, ...]
    budget: float | None
    attach: tuple[str, ...]
    mcp: tuple[str, ...]

    def spec(self, skill_ids: Mapping[str, str], model_id: str) -> JsonObject:
        result = copy.deepcopy(SPEC_DEFAULTS)
        result.update(
            name=self.name,
            description=self.description,
            instructions=self.instructions,
            capabilities=[copy.deepcopy(item) for item in self.capabilities],
            skill_ids=[skill_ids[key] for key in self.skills],
            starters=list(self.starters),
            model_profile_id=model_id,
            budget={"monthly_usd": self.budget} if self.budget is not None else None,
        )
        return result


@dataclass(frozen=True)
class Pack:
    skills: tuple[Skill, ...]
    agents: tuple[Agent, ...]


def read_skill(root: Path, key: str) -> Skill:
    folder = catalog_folder(root, "skill_gallery", key)
    metadata, body = frontmatter(folder / "SKILL.md")
    name = text_value(metadata.get("name"), f"{key}.name", maximum=64)
    if not NAME_PATTERN.fullmatch(name) or name != folder.name:
        raise InstallError(f"{key}: skill name must match its folder and use lowercase hyphens")
    description = text_value(metadata.get("description"), f"{key}.description", maximum=500)
    category = text_value(metadata.get("category"), f"{key}.category", maximum=64)
    if category != "finance":
        raise InstallError(f"{key}: this pack uses the existing finance category")
    resources: list[Resource] = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise InstallError(f"{key}: resource symlinks are not supported")
        if not path.is_file() or relative.as_posix() == "SKILL.md":
            continue
        name = relative.as_posix()
        if len(name) > 128 or path.stat().st_size > MAX_RESOURCE_BYTES:
            raise InstallError(f"{key}/{name}: exceeds the resource name or text size limit")
        try:
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise InstallError(f"{key}/{name}: only UTF-8 text resources are supported") from exc
        resources.append(Resource(name, content))
    return Skill(key, folder.name, description, body, category, tuple(resources))


def read_agent(root: Path, key: str) -> Agent:
    folder = catalog_folder(root, "agent_templates", key)
    metadata, body = frontmatter(folder / "AGENT.md")
    for field in (
        "mcp_servers",
        "subagents",
        "model_profile_id",
        "skill_ids",
        "collection_ids",
        "context_ids",
    ):
        if metadata.get(field):
            raise InstallError(
                f"{key}: {field} needs organization-specific review and is not installed automatically"
            )
    capabilities = metadata.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise InstallError(f"{key}.capabilities must be a list")
    bindings: list[JsonObject] = []
    for item in capabilities:
        binding = {"id": item} if isinstance(item, str) else object_value(item, f"{key}.capability")
        capability_id = text_value(binding.get("id"), f"{key}.capability.id")
        if set(binding) - {"id", *CAPABILITY_DEFAULTS}:
            raise InstallError(f"{key}: unsupported capability binding fields")
        if binding.get("secret_id"):
            raise InstallError(f"{key}: capability secret references require manual configuration")
        full = {**copy.deepcopy(CAPABILITY_DEFAULTS), **binding, "id": capability_id}
        object_value(full["config"], f"{key}.{capability_id}.config")
        bindings.append(full)
    ids = [str(item["id"]) for item in bindings]
    unique(ids, f"{key}.capabilities")
    if "ask_user" in ids and "drafts" not in ids:
        raise InstallError(f"{key}: ask_user must also offer drafts")
    skill_keys = strings(metadata.get("skills", []), f"{key}.skills")
    unique(skill_keys, f"{key}.skills")
    if skill_keys and "skills" not in ids:
        raise InstallError(f"{key}: bound skills need the skills capability")
    budget = metadata.get("budget_usd")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, int | float) or budget <= 0
    ):
        raise InstallError(f"{key}.budget_usd must be a positive number")
    starters = strings(metadata.get("starters", []), f"{key}.starters")
    if len(starters) > 4 or any(len(starter) > 200 for starter in starters):
        raise InstallError(f"{key}: at most four starters of 200 characters each are supported")
    return Agent(
        key=key,
        name=text_value(metadata.get("name"), f"{key}.name", maximum=128),
        description=text_value(metadata.get("description"), f"{key}.description", maximum=1000),
        instructions=body,
        capabilities=tuple(bindings),
        skills=tuple(skill_keys),
        starters=tuple(starters),
        budget=float(budget) if budget is not None else None,
        attach=tuple(strings(metadata.get("attach", []), f"{key}.attach")),
        mcp=tuple(strings(metadata.get("mcp", []), f"{key}.mcp")),
    )


def read_pack(root: Path, manifest: Path, selected_agents: Sequence[str] = ()) -> Pack:
    try:
        data = object_value(json.loads(manifest.read_text(encoding="utf-8")), "pack manifest")
    except (OSError, UnicodeError, ValueError) as exc:
        raise InstallError(f"Cannot read pack manifest {manifest}") from exc
    if type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        raise InstallError("Unsupported pack manifest schema_version")
    skill_keys = strings(data.get("skills"), "manifest.skills")
    agent_keys = strings(data.get("agents"), "manifest.agents")
    unique(skill_keys, "manifest.skills")
    unique(agent_keys, "manifest.agents")
    if not skill_keys or not agent_keys:
        raise InstallError("The pack must declare skills and agents explicitly")
    agents = tuple(read_agent(root, key) for key in agent_keys)
    unique([agent.name.casefold() for agent in agents], "agent names")
    unique([slugify(agent.name) for agent in agents], "agent handles")
    for agent in agents:
        missing = set(agent.skills) - set(skill_keys)
        if missing:
            raise InstallError(
                f"{agent.key}: skill references missing from manifest",
                details={"keys": sorted(missing)},
            )
    if selected_agents:
        unknown = set(selected_agents) - set(agent_keys)
        if unknown:
            raise InstallError("Unknown --agent selection", details={"keys": sorted(unknown)})
        agents = tuple(agent for agent in agents if agent.key in selected_agents)
        required = {key for agent in agents for key in agent.skills}
        skill_keys = [key for key in skill_keys if key in required]
    skills = tuple(read_skill(root, key) for key in skill_keys)
    unique([skill.name for skill in skills], "skill names")
    return Pack(skills, agents)


class Api(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: JsonObject | None = None,
    ) -> JsonObject: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        # A redirect must never forward the bearer credential to another origin.
        return None


class ApiClient:
    def __init__(
        self, base_url: str, token: str, organization_id: str, *, apply: bool = False
    ) -> None:
        try:
            parsed = urlsplit(base_url)
            _ = parsed.port  # Reading the property validates the port's range and syntax.
        except ValueError as exc:
            raise InstallError("--base-url is not a valid deployment URL") from exc
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
            raise InstallError(
                "--base-url must use HTTPS (HTTP is allowed only for loopback development)"
            )
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise InstallError(
                "--base-url must contain a host and no credentials, query, or fragment"
            )
        if parsed.path.rstrip("/").endswith("/api/v1"):
            raise InstallError("--base-url is the deployment URL, without /api/v1")
        if not token.strip() or "\n" in token or "\r" in token:
            raise InstallError(
                "Set T3OS_API_TOKEN to an organization API key or session access token"
            )
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.headers = {
            "Authorization": f"Bearer {token.strip()}",
            "X-Organization-Id": uuid_value(organization_id, "organization id"),
            "Accept": "application/json",
        }
        self.apply = apply
        self.opener = build_opener(NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        if method not in {"GET", "POST"} or not path.startswith("/") or path.startswith("//"):
            raise InstallError("Unsupported installer request")
        if method == "POST" and (
            not self.apply
            or not re.fullmatch(r"/(skills|agents|skills/[0-9a-f-]+/resources)", path)
        ):
            raise InstallError(
                "This installer only creates skills, resources, and draft agents with --apply"
            )
        url = self.base_url + path + ("?" + urlencode(params) if params else "")
        headers = dict(self.headers)
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
        # __init__ permits only HTTPS or loopback HTTP, and redirects are disabled.
        request = Request(url, data=body, headers=headers, method=method)  # noqa: S310
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as exc:
            # Do not echo response bodies, request bodies, or credentials into logs.
            exc.close()
            raise InstallError(
                f"HTTP {exc.code} for {method} {path}; stopped without retrying"
            ) from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise InstallError(
                f"Could not complete {method} {path}; no automatic retry. "
                "Rerun the preview to reconcile any committed write"
            ) from exc
        return object_value(result, f"{method} {path} response")


def items(response: JsonObject, label: str) -> list[JsonObject]:
    values = response.get("items")
    if not isinstance(values, list):
        raise InstallError(f"{label} response has no items list")
    return [object_value(item, label) for item in values]


def all_pages(api: Api, path: str, *, params: Mapping[str, str] | None = None) -> list[JsonObject]:
    result: list[JsonObject] = []
    seen: set[str] = set()
    total: int | None = None
    while total is None or len(result) < total:
        response = api.request(
            "GET", path, params={**(params or {}), "skip": str(len(result)), "limit": "100"}
        )
        count = response.get("total")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise InstallError(f"{path}: invalid pagination total")
        if total is not None and total != count:
            raise InstallError(f"{path}: inventory changed while paging; rerun the preview")
        total = count
        page = items(response, path)
        if len(page) > 100 or (not page and len(result) < total):
            raise InstallError(f"{path}: incomplete pagination")
        for row in page:
            row_id = uuid_value(row.get("id"), f"{path} id")
            if row_id in seen:
                raise InstallError(f"{path}: repeated id while paging; rerun the preview")
            seen.add(row_id)
        result.extend(page)
        if len(result) > total:
            raise InstallError(f"{path}: inconsistent pagination total")
    return result


def verify_context(api: Api, organization_id: str, *, apply: bool) -> None:
    response = api.request("GET", "/me/permissions")
    actual = uuid_value(response.get("organization_id"), "active organization")
    if actual != organization_id:
        raise InstallError(
            "Active organization does not match --organization-id", details={"actual": actual}
        )
    raw = response.get("permissions")
    if not isinstance(raw, list):
        raise InstallError("Cannot verify organization permissions")
    permissions = [object_value(value, "permission") for value in raw]
    scopes = {str(value.get("permission")): value.get("scope") for value in permissions}
    for permission in ("skills:view", "agents:view"):
        if scopes.get(permission) != "all":
            raise InstallError(
                f"{permission} with all scope is required to check every possible name collision"
            )
    if apply:
        for permission in ("skills:edit", "agents:edit"):
            if scopes.get(permission) not in {"own", "shared", "all"}:
                raise InstallError(f"{permission} is required to create the pack")


def verify_model_and_capabilities(api: Api, pack: Pack, model_id: str) -> None:
    profiles = items(api.request("GET", "/providers/model-profiles"), "model profiles")
    matches = [profile for profile in profiles if profile.get("id") == model_id]
    if len(matches) != 1:
        raise InstallError(
            "The selected model profile is not uniquely available in this organization"
        )
    profile = matches[0]
    if profile.get("chat_capable") is not True or profile.get("missing_key") is not False:
        raise InstallError("The selected model must be chat-capable and have usable authentication")
    if profile.get("usage_scope") != "organization":
        raise InstallError(
            "Select an organization model profile for these organization-visible drafts"
        )
    catalog = items(api.request("GET", "/agents/capabilities"), "capabilities")
    ids = {row.get("id") for row in catalog if isinstance(row.get("id"), str)}
    required = {str(binding["id"]) for agent in pack.agents for binding in agent.capabilities}
    missing = required - ids
    if missing:
        raise InstallError("Deployment lacks pack capabilities", details={"ids": sorted(missing)})
    if any(skill.name in ids for skill in pack.skills):
        raise InstallError("A skill name collides with a registered capability")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:64] or "agent"
    return f"{slug}-agent" if slug in {"channel", "all", "here", "everyone"} else slug


def match_row(rows: Sequence[JsonObject], name: str, *, agent: bool = False) -> JsonObject | None:
    matches = [
        row
        for row in rows
        if str(row.get("name", "")).casefold() == name.casefold()
        or (agent and row.get("slug") == slugify(name))
    ]
    if len(matches) > 1:
        raise InstallError(f"Ambiguous existing name or handle: {name}")
    if matches and matches[0].get("name") != name:
        raise InstallError(f"Existing name or handle conflicts with: {name}")
    return matches[0] if matches else None


def assert_fields(actual: JsonObject, expected: JsonObject, label: str) -> None:
    changed = sorted(key for key, value in expected.items() if actual.get(key) != value)
    if changed:
        raise InstallError(
            f"Existing {label} differs; no content will be overwritten", details={"fields": changed}
        )


def inspect_skill(api: Api, skill: Skill, skill_id: str) -> tuple[Resource, ...]:
    detail = api.request("GET", f"/skills/{skill_id}")
    if uuid_value(detail.get("id"), "skill id") != skill_id:
        raise InstallError("Skill detail returned a different id")
    assert_fields(detail, skill.payload(), f"skill {skill.name}")
    raw = detail.get("resources")
    if not isinstance(raw, list):
        raise InstallError(f"{skill.name}: resource inventory is absent")
    summaries = [object_value(value, "resource summary") for value in raw]
    names = [text_value(summary.get("name"), "resource name") for summary in summaries]
    unique(names, f"{skill.name} resource names")
    wanted = {resource.name: resource for resource in skill.resources}
    extra = set(names) - wanted.keys()
    if extra:
        raise InstallError(
            f"{skill.name}: existing extra resources are a customization",
            details={"names": sorted(extra)},
        )
    for summary in summaries:
        name = text_value(summary.get("name"), "resource name")
        resource_id = uuid_value(summary.get("id"), "resource id")
        detail = api.request("GET", f"/skills/{skill_id}/resources/{resource_id}")
        assert_fields(detail, wanted[name].payload(), f"resource {skill.name}/{name}")
    return tuple(resource for resource in skill.resources if resource.name not in names)


def inspect_agent(api: Api, agent: Agent, agent_id: str, spec: JsonObject) -> None:
    detail = api.request("GET", f"/agents/{agent_id}")
    expected: JsonObject = {
        "id": agent_id,
        "name": agent.name,
        "description": agent.description,
        "status": "draft",
        "visibility": "org",
        "current_version_id": None,
        "workflow_id": None,
        "a2a_enabled": False,
        "categories": ["finance"],
        "tags": TAGS,
        "draft_spec": spec,
    }
    assert_fields(detail, expected, f"agent {agent.name}")


@dataclass
class PlannedSkill:
    skill: Skill
    existing_id: str | None
    missing: tuple[Resource, ...]


@dataclass
class PlannedAgent:
    agent: Agent
    existing_id: str | None


def reconcile(
    api: Api,
    pack: Pack,
    organization_id: str,
    model_id: str,
    *,
    apply: bool = False,
    confirmed_id: str | None = None,
) -> JsonObject:
    organization_id = uuid_value(organization_id, "organization id")
    model_id = uuid_value(model_id, "model profile id")
    if apply and confirmed_id != organization_id:
        raise InstallError(
            "--apply requires --confirm-organization-id with the exact organization UUID"
        )
    verify_context(api, organization_id, apply=apply)
    verify_model_and_capabilities(api, pack, model_id)
    skill_rows = all_pages(api, "/skills", params={"sort": "name"})
    agent_rows = all_pages(api, "/agents", params={"include_archived": "true"})
    skill_ids: dict[str, str] = {}
    skill_plan: list[PlannedSkill] = []
    agent_plan: list[PlannedAgent] = []
    for skill in pack.skills:
        row = match_row(skill_rows, skill.name)
        skill_id = uuid_value(row.get("id"), "skill id") if row is not None else None
        missing = inspect_skill(api, skill, skill_id) if skill_id else skill.resources
        skill_plan.append(PlannedSkill(skill, skill_id, missing))
        if skill_id:
            skill_ids[skill.key] = skill_id
    for agent in pack.agents:
        row = match_row(agent_rows, agent.name, agent=True)
        agent_id = uuid_value(row.get("id"), "agent id") if row is not None else None
        if agent_id:
            if any(key not in skill_ids for key in agent.skills):
                raise InstallError(
                    f"Existing {agent.name} cannot match: one of its expected skills is missing"
                )
            inspect_agent(api, agent, agent_id, agent.spec(skill_ids, model_id))
        agent_plan.append(PlannedAgent(agent, agent_id))
    report: JsonObject = {
        "mode": "apply" if apply else "dry-run",
        "organization_id": organization_id,
        "model_profile_id": model_id,
        "skills": [
            {
                "key": item.skill.key,
                "action": "create"
                if item.existing_id is None
                else "add-resources"
                if item.missing
                else "unchanged",
                "resources_to_create": [resource.name for resource in item.missing],
            }
            for item in skill_plan
        ],
        "agents": [
            {
                "key": item.agent.key,
                "action": "create-draft" if item.existing_id is None else "unchanged",
                "attach_manually": list(item.agent.attach),
                "suggested_mcp": list(item.agent.mcp),
            }
            for item in agent_plan
        ],
    }
    if not apply:
        return report
    # Recheck authority after the complete preflight and before the first write.
    verify_context(api, organization_id, apply=True)
    for item in skill_plan:
        skill = item.skill
        if item.existing_id is None:
            created = api.request("POST", "/skills", payload=skill.payload())
            item.existing_id = uuid_value(created.get("id"), "created skill id")
        missing = inspect_skill(api, skill, item.existing_id)
        for resource in missing:
            created = api.request(
                "POST", f"/skills/{item.existing_id}/resources", payload=resource.payload()
            )
            assert_fields(
                created, resource.payload(), f"created resource {skill.name}/{resource.name}"
            )
        skill_ids[skill.key] = item.existing_id
    agent_ids: JsonObject = {}
    for item in agent_plan:
        spec = item.agent.spec(skill_ids, model_id)
        if item.existing_id is None:
            created = api.request(
                "POST",
                "/agents",
                payload={
                    "spec": spec,
                    "from_starter": False,
                    "visibility": "org",
                    "categories": ["finance"],
                    "tags": TAGS,
                },
            )
            item.existing_id = uuid_value(created.get("id"), "created agent id")
        inspect_agent(api, item.agent, item.existing_id, spec)
        agent_ids[item.agent.key] = item.existing_id
    report["skill_ids"] = dict(skill_ids)
    report["agent_ids"] = agent_ids
    report["published"] = False
    return report


def run(args: argparse.Namespace) -> JsonObject:
    pack = read_pack(args.repo_root, args.manifest, args.agent)
    if args.check:
        if args.apply:
            raise InstallError("--check cannot be combined with --apply")
        return {
            "mode": "local-check",
            "skills": len(pack.skills),
            "resources": sum(len(skill.resources) for skill in pack.skills),
            "agents": [agent.key for agent in pack.agents],
        }
    if not args.base_url or not args.organization_id or not args.model_profile_id:
        raise InstallError(
            "Preview/apply requires --base-url, --organization-id, and --model-profile-id"
        )
    api = ApiClient(
        args.base_url, os.environ.get("T3OS_API_TOKEN", ""), args.organization_id, apply=args.apply
    )
    return reconcile(
        api,
        pack,
        args.organization_id,
        args.model_profile_id,
        apply=args.apply,
        confirmed_id=args.confirm_organization_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--agent", action="append", default=[], help="Install only this manifest key (repeatable)"
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate local pack files without any network calls"
    )
    parser.add_argument("--base-url", help="Deployment URL, without /api/v1")
    parser.add_argument("--organization-id")
    parser.add_argument("--model-profile-id")
    parser.add_argument(
        "--apply", action="store_true", help="Create missing content after a full preflight"
    )
    parser.add_argument(
        "--confirm-organization-id", help="Repeat the exact organization UUID to allow creation"
    )
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except InstallError as exc:
        sys.stderr.write(json.dumps({"error": exc.message, "details": exc.details}) + "\n")
        return 1
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
