"""Create-only installer checks; no backend import, network, or database needed."""

import copy
import io
import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import install

ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
MODEL = "33333333-3333-4333-8333-333333333333"


def pack_fixture() -> install.Pack:
    skill = install.Skill(
        "finance/example-accounting",
        "example-accounting",
        "Example reconciliation procedure.",
        "Preserve evidence and report unresolved differences.",
        "finance",
        (
            install.Resource("SOURCE.md", "Pinned source."),
            install.Resource("references/checks.md", "Check totals."),
        ),
    )
    agent = install.Agent(
        key="finance/example-agent",
        name="Example Accounting Agent",
        description="Prepares a reconciliation for review.",
        instructions="Read the assigned skill and reconcile the supplied evidence.",
        capabilities=({**copy.deepcopy(install.CAPABILITY_DEFAULTS), "id": "skills"},),
        skills=(skill.key,),
        starters=("Prepare the reconciliation.",),
        budget=30,
        attach=("collection", "sandbox"),
        mcp=("postgres",),
    )
    return install.Pack((skill,), (agent,))


class FakeApi:
    def __init__(self) -> None:
        self.organization_id = ORG
        self.permissions = {
            "skills:view": "all",
            "agents:view": "all",
            "skills:edit": "all",
            "agents:edit": "all",
        }
        self.model: install.JsonObject = {
            "id": MODEL,
            "chat_capable": True,
            "missing_key": False,
            "usage_scope": "organization",
        }
        self.skills: dict[str, install.JsonObject] = {}
        self.resources: dict[str, install.JsonObject] = {}
        self.agents: dict[str, install.JsonObject] = {}
        self.requests: list[tuple[str, str, dict[str, str], install.JsonObject | None]] = []
        self.next_id = 1
        self.page_size = 100
        self.fail_after_resource_create = False
        self.fail_after_agent_create = False

    def new_id(self) -> str:
        value = f"00000000-0000-4000-8000-{self.next_id:012d}"
        self.next_id += 1
        return value

    def writes(self) -> list[tuple[str, str, dict[str, str], install.JsonObject | None]]:
        return [request for request in self.requests if request[0] != "GET"]

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: install.JsonObject | None = None,
    ) -> install.JsonObject:
        self.requests.append((method, path, dict(params or {}), copy.deepcopy(payload)))
        if method == "GET":
            return copy.deepcopy(self.read(path, params or {}))
        if method != "POST" or payload is None:
            raise AssertionError(f"Unexpected request: {method} {path}")
        row_id = self.new_id()
        if path == "/skills":
            row = {**payload, "id": row_id, "resources": []}
            self.skills[row_id] = row
        elif path.endswith("/resources"):
            skill_id = path.split("/")[2]
            row = {**payload, "id": row_id}
            self.resources[row_id] = row
            resources = self.skills[skill_id]["resources"]
            assert isinstance(resources, list)
            resources.append({"id": row_id, "name": payload["name"]})
            if self.fail_after_resource_create:
                self.fail_after_resource_create = False
                raise install.InstallError("Response lost after resource commit")
        elif path == "/agents":
            spec = install.object_value(payload["spec"], "spec")
            row = {
                "id": row_id,
                "slug": install.slugify(str(spec["name"])),
                "name": spec["name"],
                "description": spec["description"],
                "status": "draft",
                "visibility": payload["visibility"],
                "current_version_id": None,
                "workflow_id": None,
                "a2a_enabled": False,
                "categories": payload["categories"],
                "tags": payload["tags"],
                "draft_spec": spec,
            }
            self.agents[row_id] = row
            if self.fail_after_agent_create:
                self.fail_after_agent_create = False
                raise install.InstallError("Response lost after agent commit")
        else:
            raise AssertionError(f"Unexpected mutation: {path}")
        return copy.deepcopy(row)

    def read(self, path: str, params: Mapping[str, str]) -> install.JsonObject:
        if path == "/me/permissions":
            return {
                "organization_id": self.organization_id,
                "permissions": [
                    {"permission": key, "scope": scope} for key, scope in self.permissions.items()
                ],
            }
        if path == "/providers/model-profiles":
            return {"items": [self.model], "total": 1}
        if path == "/agents/capabilities":
            return {"items": [{"id": "skills"}], "total": 1}
        if path in {"/skills", "/agents"}:
            rows = list(self.skills.values() if path == "/skills" else self.agents.values())
            skip = int(params["skip"])
            return {"items": rows[skip : skip + self.page_size], "total": len(rows)}
        parts = path.split("/")
        if parts[1] == "skills" and len(parts) == 3:
            return self.skills[parts[2]]
        if parts[1] == "skills" and len(parts) == 5:
            return self.resources[parts[4]]
        if parts[1] == "agents" and len(parts) == 3:
            return self.agents[parts[2]]
        raise AssertionError(f"Unexpected read: {path}")


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.pack = pack_fixture()

    def apply(self) -> install.JsonObject:
        return install.reconcile(self.api, self.pack, ORG, MODEL, apply=True, confirmed_id=ORG)

    def test_wrong_active_organization_stops_before_any_write(self) -> None:
        self.api.organization_id = OTHER_ORG
        with self.assertRaisesRegex(install.InstallError, "Active organization"):
            self.apply()
        self.assertEqual(self.api.writes(), [])
        self.assertEqual(len(self.api.requests), 1)

    def test_apply_needs_exact_confirmation_before_network_access(self) -> None:
        with self.assertRaisesRegex(install.InstallError, "exact organization UUID"):
            install.reconcile(self.api, self.pack, ORG, MODEL, apply=True, confirmed_id=OTHER_ORG)
        self.assertEqual(self.api.requests, [])

    def test_default_preview_only_reads_and_keeps_requirements_unbound(self) -> None:
        report = install.reconcile(self.api, self.pack, ORG, MODEL)
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(self.api.writes(), [])
        self.assertEqual(self.api.skills, {})
        self.assertEqual(self.api.agents, {})
        agents = report["agents"]
        assert isinstance(agents, list)
        self.assertEqual(agents[0]["attach_manually"], ["collection", "sandbox"])

    def test_second_apply_is_unchanged_and_uses_actual_skill_uuids(self) -> None:
        first = self.apply()
        writes = len(self.api.writes())
        second = self.apply()
        self.assertEqual(len(self.api.writes()), writes)
        self.assertEqual(first["skill_ids"], second["skill_ids"])
        self.assertEqual(first["agent_ids"], second["agent_ids"])
        agent = next(iter(self.api.agents.values()))
        spec = install.object_value(agent["draft_spec"], "spec")
        self.assertEqual(spec["skill_ids"], list(self.api.skills))
        self.assertEqual(spec["model_profile_id"], MODEL)
        self.assertEqual(spec["mcp_servers"], [])
        self.assertEqual(spec["collection_ids"], [])
        self.assertEqual(agent["status"], "draft")
        self.assertFalse(second["published"])
        self.assertTrue(all(request[0] == "POST" for request in self.api.writes()))

    def test_lost_resource_response_resumes_without_duplicate_resources(self) -> None:
        self.api.fail_after_resource_create = True
        with self.assertRaisesRegex(install.InstallError, "Response lost"):
            self.apply()
        self.assertEqual(len(self.api.skills), 1)
        self.assertEqual(len(self.api.resources), 1)
        self.assertEqual(len(self.api.agents), 0)
        self.apply()
        self.assertEqual(len(self.api.skills), 1)
        self.assertEqual(len(self.api.resources), 2)
        self.assertEqual(len(self.api.agents), 1)
        names = [row["name"] for row in self.api.resources.values()]
        self.assertEqual(sorted(names), ["SOURCE.md", "references/checks.md"])

    def test_lost_agent_response_resumes_without_creating_another_agent(self) -> None:
        self.api.fail_after_agent_create = True
        with self.assertRaisesRegex(install.InstallError, "Response lost"):
            self.apply()
        self.assertEqual(len(self.api.agents), 1)
        writes = len(self.api.writes())
        self.apply()
        self.assertEqual(len(self.api.writes()), writes)

    def test_late_agent_conflict_is_found_before_missing_skill_resources_are_added(self) -> None:
        self.apply()
        skill = next(iter(self.api.skills.values()))
        skill["resources"] = []
        agent = next(iter(self.api.agents.values()))
        agent["draft_spec"]["instructions"] = "Customized instructions."
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "differs"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_different_skill_body_is_not_overwritten(self) -> None:
        self.apply()
        next(iter(self.api.skills.values()))["content"] = "Firm-specific procedure."
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "differs"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_different_resource_is_not_overwritten(self) -> None:
        self.apply()
        next(iter(self.api.resources.values()))["content"] = "Firm-specific reference."
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "differs"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_extra_resource_is_treated_as_customization(self) -> None:
        self.apply()
        skill_id = next(iter(self.api.skills))
        self.api.request(
            "POST",
            f"/skills/{skill_id}/resources",
            payload={"name": "custom.md", "content": "Custom"},
        )
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "extra resources"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_duplicate_agent_names_are_ambiguous(self) -> None:
        self.apply()
        duplicate = copy.deepcopy(next(iter(self.api.agents.values())))
        duplicate_id = self.api.new_id()
        duplicate["id"] = duplicate_id
        self.api.agents[duplicate_id] = duplicate
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "Ambiguous"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_slug_collision_with_a_different_name_is_a_conflict(self) -> None:
        self.apply()
        next(iter(self.api.agents.values()))["name"] = "Another Name"
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "name or handle conflicts"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_published_agents_are_left_for_manual_review(self) -> None:
        self.apply()
        next(iter(self.api.agents.values()))["status"] = "published"
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "differs"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_unknown_or_changed_spec_fields_are_not_silently_ignored(self) -> None:
        self.apply()
        next(iter(self.api.agents.values()))["draft_spec"]["future_behavior"] = True
        self.api.requests.clear()
        with self.assertRaisesRegex(install.InstallError, "differs"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_limited_visibility_cannot_claim_collision_safety(self) -> None:
        self.api.permissions["skills:view"] = "own"
        with self.assertRaisesRegex(install.InstallError, "all scope"):
            self.apply()
        self.assertEqual(self.api.writes(), [])

    def test_unusable_or_personal_model_is_refused(self) -> None:
        for field, value in (
            ("chat_capable", False),
            ("missing_key", True),
            ("usage_scope", "personal"),
        ):
            with self.subTest(field=field):
                api = FakeApi()
                api.model[field] = value
                with self.assertRaises(install.InstallError):
                    install.reconcile(api, self.pack, ORG, MODEL, apply=True, confirmed_id=ORG)
                self.assertEqual(api.writes(), [])

    def test_lists_are_paged_until_the_declared_total(self) -> None:
        for index in range(3):
            row_id = self.api.new_id()
            self.api.skills[row_id] = {"id": row_id, "name": f"unrelated-{index}"}
        self.api.page_size = 1
        install.reconcile(self.api, self.pack, ORG, MODEL)
        calls = [request for request in self.api.requests if request[1] == "/skills"]
        self.assertEqual([call[2]["skip"] for call in calls], ["0", "1", "2"])

    def test_repeated_page_is_rejected_instead_of_looping_or_missing_conflicts(self) -> None:
        row = {"id": self.api.new_id(), "name": "example"}
        broken = Mock()
        broken.request.return_value = {"items": [row], "total": 2}
        with self.assertRaisesRegex(install.InstallError, "repeated id"):
            install.all_pages(broken, "/skills")


class PackReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.skill_folder = (
            self.root / "backend/app/core/catalog/skill_gallery/finance/example-accounting"
        )
        self.skill_folder.mkdir(parents=True)
        (self.skill_folder / "SKILL.md").write_text(
            "---\nname: example-accounting\ndescription: Example accounting.\ncategory: finance\n---\nRead evidence.\n",
            encoding="utf-8",
        )
        (self.skill_folder / "SOURCE.md").write_text("Pinned source.\n", encoding="utf-8")
        self.agent_folder = (
            self.root / "backend/app/core/catalog/agent_templates/finance/example-agent"
        )
        self.agent_folder.mkdir(parents=True)
        (self.agent_folder / "AGENT.md").write_text(
            "---\nname: Example Agent\ndescription: Example agent.\ncapabilities: [skills]\n"
            "skills: [finance/example-accounting]\nattach: [sandbox]\n---\nRead the assigned skill.\n",
            encoding="utf-8",
        )
        self.write_manifest()

    def write_manifest(self, **extra: install.Json) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skills": ["finance/example-accounting"],
                    "agents": ["finance/example-agent"],
                    **extra,
                }
            ),
            encoding="utf-8",
        )

    def test_manifest_is_explicit_and_extra_source_metadata_is_allowed(self) -> None:
        self.write_manifest(id="accounting-firm", sources=[{"commit": "abc"}])
        pack = install.read_pack(self.root, self.manifest)
        self.assertEqual(len(pack.skills), 1)
        self.assertEqual(pack.skills[0].resources[0].content, "Pinned source.")
        self.assertEqual(pack.agents[0].attach, ("sandbox",))

    def test_agent_selection_loads_only_its_transitive_skills(self) -> None:
        self.write_manifest(skills=["finance/example-accounting", "finance/not-selected"])
        pack = install.read_pack(self.root, self.manifest, ["finance/example-agent"])
        self.assertEqual([skill.key for skill in pack.skills], ["finance/example-accounting"])

    def test_absent_skill_reference_is_refused(self) -> None:
        self.write_manifest(skills=["finance/different-skill"])
        with self.assertRaisesRegex(install.InstallError, "references missing"):
            install.read_pack(self.root, self.manifest)

    def test_manifest_path_cannot_escape_catalog_root(self) -> None:
        self.write_manifest(agents=["../example-agent"])
        with self.assertRaisesRegex(install.InstallError, "Unsupported catalog key"):
            install.read_pack(self.root, self.manifest)

    def test_binary_resources_are_refused_before_network_work(self) -> None:
        (self.skill_folder / "example.pdf").write_bytes(b"%PDF-\xff")
        with self.assertRaisesRegex(install.InstallError, "UTF-8"):
            install.read_pack(self.root, self.manifest)

    def test_resource_symlinks_are_refused(self) -> None:
        (self.skill_folder / "linked.md").symlink_to(self.skill_folder / "SOURCE.md")
        with self.assertRaisesRegex(install.InstallError, "symlinks"):
            install.read_pack(self.root, self.manifest)

    def test_organization_bindings_cannot_hide_in_a_template(self) -> None:
        path = self.agent_folder / "AGENT.md"
        content = path.read_text(encoding="utf-8").replace(
            "attach: [sandbox]", f"model_profile_id: {MODEL}"
        )
        path.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(install.InstallError, "organization-specific review"):
            install.read_pack(self.root, self.manifest)


class HttpClientTests(unittest.TestCase):
    def test_verified_auth_headers_and_api_prefix_are_used(self) -> None:
        api = install.ApiClient("https://deployment.example", "test-token", ORG)
        api.opener = Mock()
        api.opener.open.return_value = io.BytesIO(b'{"items": [], "total": 0}')
        api.request("GET", "/skills", params={"skip": "0", "limit": "100"})
        request = api.opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://deployment.example/api/v1/skills?skip=0&limit=100"
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(request.get_header("X-organization-id"), ORG)

    def test_transport_blocks_mutations_in_preview_mode(self) -> None:
        api = install.ApiClient("https://deployment.example", "test-token", ORG)
        with self.assertRaisesRegex(install.InstallError, "only creates"):
            api.request("POST", "/skills", payload={})

    def test_transport_never_accepts_publish_or_delete(self) -> None:
        api = install.ApiClient("https://deployment.example", "test-token", ORG, apply=True)
        for method, path in (("POST", f"/agents/{MODEL}/publish"), ("DELETE", f"/skills/{MODEL}")):
            with self.subTest(method=method), self.assertRaises(install.InstallError):
                api.request(method, path, payload={})

    def test_http_errors_do_not_echo_server_bodies_or_retry_writes(self) -> None:
        api = install.ApiClient("https://deployment.example", "test-token", ORG, apply=True)
        api.opener = Mock()
        response_error = HTTPError("https://deployment.example", 500, "secret content", {}, None)
        api.opener.open.side_effect = response_error
        with self.assertRaisesRegex(install.InstallError, "stopped without retrying") as error:
            api.request("POST", "/skills", payload={})
        self.assertNotIn("secret content", str(error.exception))
        self.assertEqual(api.opener.open.call_count, 1)
        self.assertTrue(response_error.closed)

    def test_credentials_are_not_sent_over_remote_http_or_url_userinfo(self) -> None:
        for url in ("http://deployment.example", "https://user:password@deployment.example"):
            with self.subTest(url=url), self.assertRaises(install.InstallError):
                install.ApiClient(url, "test-token", ORG)

    def test_redirects_are_refused(self) -> None:
        result = install.NoRedirect().redirect_request(
            Mock(), None, 302, "Found", {}, "https://other.example"
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
