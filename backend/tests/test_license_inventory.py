"""What the licence inventory may conclude, and what it has to leave to a person.

`scripts/license_inventory.py` generates `THIRD_PARTY_NOTICES.md` and gates the
`security` job on it, so the interesting failures are the quiet ones: a component
with no licence metadata rendered as if it had one, a copyleft dependency passing
because nobody was asked, a review decision surviving the upgrade that changed the
licence it reviewed. Each of those is a test here.

The collectors that read a real virtualenv and a real `node_modules` are exercised
against small fixture trees, so the suite is about the rules and not about which
packages happen to be installed on the machine running it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "license_inventory.py"
_NAME = "license_inventory_under_test"
_spec = importlib.util.spec_from_file_location(_NAME, _SCRIPT)
assert _spec is not None and _spec.loader is not None
inventory = importlib.util.module_from_spec(_spec)
# `@dataclass` resolves annotations through `sys.modules[cls.__module__]`.
sys.modules[_NAME] = inventory
_spec.loader.exec_module(inventory)

MIT_TEXT = (
    "MIT License\n\nCopyright (c) 2020 Somebody\n\nPermission is hereby granted, free of charge, "
    "to any person obtaining a copy of this software... The above copyright notice and this "
    "permission notice shall be included in all copies."
)
BSD3_TEXT = (
    "Redistribution and use in source and binary forms, with or without modification, are "
    "permitted provided that the following conditions are met: ... Neither the name of the "
    "copyright holder nor the names of its contributors may be used to endorse or promote products."
)
BSD2_TEXT = (
    "Redistribution and use in source and binary forms, with or without modification, are "
    "permitted provided that the following conditions are met: 1. Redistributions of source code "
    "must retain the above copyright notice. 2. Redistributions in binary form must reproduce it."
)


class TestClassifyExpression:
    @pytest.mark.parametrize(
        "expression", ["MIT", "Apache-2.0", "MIT OR Apache-2.0", "BSD-3-Clause AND MIT"]
    )
    def test_permissive_terms_are_permissive(self, expression: str) -> None:
        assert inventory.classify_expression(expression) == "permissive"

    @pytest.mark.parametrize(
        "expression", ["MPL-2.0", "LGPL-3.0-or-later", "AGPL-3.0-only", "MPL-2.0 AND MIT"]
    )
    def test_a_review_family_anywhere_in_an_and_needs_review(self, expression: str) -> None:
        assert inventory.classify_expression(expression) == "review"

    def test_or_lets_the_distributor_choose_the_permissive_alternative(self) -> None:
        assert inventory.classify_expression("Artistic-1.0-Perl OR GPL-2.0-or-later") == "review"
        assert inventory.classify_expression("GPL-2.0-or-later OR MIT") == "permissive"
        assert inventory.classify_expression("MPL-2.0 AND (Apache-2.0 OR MIT)") == "review"

    def test_a_with_exception_reads_as_its_base_licence(self) -> None:
        assert inventory.classify_expression("LGPL-3.0-or-later WITH openssl-exception") == "review"

    @pytest.mark.parametrize(
        "expression", ["Proprietary", "MIT AND Something-Else", "(MIT", "MIT OR", "SEE LICENSE"]
    )
    def test_anything_the_policy_does_not_name_is_unknown(self, expression: str) -> None:
        """Unknown wins: an unrecognised identifier next to MIT is still a question."""
        assert inventory.classify_expression(expression) == "unknown"


class TestSpdxIdentifiers:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("MIT", ["MIT"]),
            ("(MIT OR Apache-2.0)", ["MIT", "Apache-2.0"]),
            ("MIT AND ISC AND MIT", ["MIT", "ISC"]),
            ("LGPL-3.0-or-later WITH openssl-exception", ["LGPL-3.0-or-later"]),
            ("MPL-2.0 AND (Apache-2.0 OR MIT)", ["MPL-2.0", "Apache-2.0", "MIT"]),
        ],
    )
    def test_identifiers_without_operators_or_exceptions(
        self, expression: str, expected: list[str]
    ) -> None:
        assert inventory.spdx_identifiers(expression) == expected


class TestLicenseFromText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (MIT_TEXT, "MIT"),
            (BSD3_TEXT, "BSD-3-Clause"),
            (BSD2_TEXT, "BSD-2-Clause"),
            ("Apache License\nVersion 2.0, January 2004\nTERMS AND CONDITIONS", "Apache-2.0"),
            ("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License", "AGPL-3.0-only"),
            (
                "psycopg2 is free software: you can redistribute it under the terms of the GNU Lesser "
                "General Public License, either version 3 of the License, or (at your option) any later version.",
                "LGPL-3.0-or-later",
            ),
            ("Mozilla Public License Version 2.0\n1. Definitions", "MPL-2.0"),
            (
                "Permission to use, copy, modify, and/or distribute this software for any purpose with or "
                "without fee is hereby granted, provided that the above copyright notice appear in all copies.",
                "ISC",
            ),
            (
                "Permission to use, copy, modify, and/or distribute this software for any purpose with or "
                "without fee is hereby granted.",
                "0BSD",
            ),
            (
                "This is free and unencumbered software released into the public domain.",
                "Unlicense",
            ),
        ],
    )
    def test_distinctive_texts_are_named(self, text: str, expected: str) -> None:
        assert inventory.license_from_text(text) == expected

    def test_an_unfamiliar_text_is_a_question(self) -> None:
        assert (
            inventory.license_from_text("You may do as you please with this code. No warranty.")
            is None
        )


class TestPythonLicense:
    def test_classifiers_decide_only_when_all_are_recognised_and_agree(self) -> None:
        mit = ["License :: OSI Approved :: MIT License"]
        dual = [
            "License :: OSI Approved :: Artistic License",
            "License :: OSI Approved :: GNU General Public License (GPL)",
            "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        ]

        assert inventory.python_license("", "", mit, []) == ("MIT", "classifier")
        assert inventory.python_license("", "", dual, [])[0] is None
        assert inventory.python_license("", "", dual, [MIT_TEXT]) == ("MIT", "licence file text")

    def test_an_override_yields_to_metadata_that_names_a_licence(self) -> None:
        policy = inventory.Policy({"python:lib": inventory.Override("ISC", "read upstream")}, {})

        assert inventory.apply_override(
            policy, "python:lib", None, "no readable licence metadata"
        ) == (
            "ISC",
            "override: read upstream",
        )
        assert inventory.apply_override(policy, "python:lib", "MIT", "License-Expression") == (
            "MIT",
            "License-Expression",
        )

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            (("Ada Lovelace", "ada@example.invalid", "", ""), "Ada Lovelace"),
            (("", "Ada Lovelace <ada@example.invalid>", "", ""), "Ada Lovelace"),
            (
                ("", '"Ada Lovelace" <a@x>, Grace Hopper <g@x>', "Ada Lovelace", ""),
                "Ada Lovelace, Grace Hopper",
            ),
            (("", "", "", "team@example.invalid"), ""),
            ((None, None, None, None), ""),
        ],
    )
    def test_people_reads_names_and_drops_addresses(
        self, fields: tuple[object, ...], expected: str
    ) -> None:
        assert inventory.people(*fields) == expected


class TestNodeManifests:
    def test_the_modern_field_is_read_as_an_expression(self) -> None:
        assert inventory.node_license({"license": "(MIT OR Apache-2.0)"}, []) == (
            "MIT OR Apache-2.0",
            "package.json license",
        )
        assert inventory.node_license({"license": {"type": "ISC"}}, []) == (
            "ISC",
            "package.json license",
        )

    def test_the_legacy_array_is_joined_as_alternatives(self) -> None:
        manifest = {"licenses": [{"type": "MIT"}, {"type": "Apache-2.0"}]}
        assert inventory.node_license(manifest, []) == (
            "MIT OR Apache-2.0",
            "package.json licenses",
        )

    def test_see_license_in_and_a_missing_field_fall_through_to_the_file(self) -> None:
        assert inventory.node_license({"license": "SEE LICENSE IN LICENSE.txt"}, [BSD3_TEXT]) == (
            "BSD-3-Clause",
            "licence file text",
        )
        assert inventory.node_license({}, []) == (None, "no readable licence metadata")

    def test_unlicensed_is_a_refusal_not_a_licence(self) -> None:
        assert inventory.node_license({"license": "UNLICENSED"}, [])[0] is None

    @pytest.mark.parametrize(
        ("manifest", "expected"),
        [
            ({}, True),
            ({"os": ["linux"], "cpu": ["x64"]}, True),
            ({"os": ["linux"], "cpu": ["arm64"], "libc": ["glibc"]}, True),
            ({"os": ["darwin"], "cpu": ["arm64"]}, False),
            ({"os": ["win32"]}, False),
            ({"os": ["linux"], "cpu": ["s390x"]}, False),
            ({"os": ["linux"], "cpu": ["x64"], "libc": ["musl"]}, False),
            ({"os": ["!linux"]}, False),
            ({"os": ["!darwin", "!win32"]}, True),
            ({"cpu": ["!arm", "!ia32"]}, True),
            ({"libc": ["!musl"]}, True),
            ({"os": ["linux"], "cpu": ["arm64", "!arm64"]}, False),
        ],
    )
    def test_platform_builds_are_kept_only_when_the_image_can_contain_them(
        self, manifest: dict[str, object], expected: bool
    ) -> None:
        assert inventory.builds_for_linux(manifest) is expected

    def test_source_urls_are_normalised_to_one_spelling(self) -> None:
        assert inventory.node_source(
            {"repository": {"url": "git+https://github.com/a/b.git"}}, "b", "1"
        ) == ("https://github.com/a/b")
        assert inventory.node_source({"repository": "a/b"}, "b", "1") == "https://github.com/a/b"
        assert inventory.node_source(
            {"repository": {"url": "git@github.com:a/b.git"}}, "b", "1"
        ) == ("https://github.com/a/b")
        assert inventory.node_source({}, "b", "1.2.3") == "https://www.npmjs.com/package/b/v/1.2.3"

    def test_the_lockfile_lists_every_resolved_version_including_nested_copies(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "bun.lock"
        lock.write_text(
            '{\n  "packages": {\n    "a": ["a@1.0.0", "", {}, "sha512-x",],\n'
            '    "b/a": ["a@2.0.0", "", {}, "sha512-y",],\n    "@s/c": ["@s/c@3.1.4", "", {}, "sha512-z",],\n  },\n}\n'
        )
        assert inventory.lockfile_versions(lock) == {"a": {"1.0.0", "2.0.0"}, "@s/c": {"3.1.4"}}


def _node_package(
    root: Path,
    name: str,
    version: str,
    manifest: dict[str, object],
    license_text: str | None = None,
) -> None:
    directory = root / "node_modules" / name
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps({"name": name, "version": version, **manifest})
    )
    if license_text is not None:
        (directory / "LICENSE").write_text(license_text)


class TestNodeComponent:
    def test_an_override_yields_to_metadata_that_names_a_licence(self) -> None:
        policy = inventory.Policy({"npm:lib": inventory.Override("ISC", "read upstream")}, {})

        declared = inventory.node_component(policy, {"license": "MIT"}, "lib", "1.0", ["text"])
        silent = inventory.node_component(policy, {}, "lib", "1.0", [])

        assert (declared.license, declared.evidence) == ("MIT", "package.json license")
        assert (silent.license, silent.evidence) == ("ISC", "override: read upstream")

    def test_a_missing_licence_file_and_the_author_are_recorded(self) -> None:
        manifest = {"license": "MIT", "author": {"name": "Ada"}, "contributors": ["Grace <g@x>"]}

        on_disk = inventory.node_component(inventory.Policy({}, {}), manifest, "a", "1", [])
        from_index = inventory.node_component(inventory.Policy({}, {}), manifest, "a", "1", None)

        assert (on_disk.license_file, on_disk.attribution) == (False, "Ada, Grace <g@x>")
        assert from_index.license_file is None


class TestNodeComponents:
    def test_the_production_closure_is_walked_and_dev_dependencies_are_not(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"app-dep": "^1"}, "devDependencies": {"only-dev": "^1"}})
        )
        (tmp_path / "bun.lock").write_text('{"packages": {}}')
        _node_package(
            tmp_path, "app-dep", "1.0.0", {"license": "MIT", "dependencies": {"transitive": "^2"}}
        )
        _node_package(tmp_path, "transitive", "2.0.0", {}, BSD2_TEXT)
        _node_package(tmp_path, "only-dev", "1.0.0", {"license": "MIT"})

        components = inventory.node_components(inventory.Policy({}, {}), tmp_path)

        assert [(c.name, c.version, c.license, c.evidence) for c in components] == [
            ("app-dep", "1.0.0", "MIT", "package.json license"),
            ("transitive", "2.0.0", "BSD-2-Clause", "licence file text"),
        ]

    def test_a_nested_copy_is_resolved_the_way_require_does(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"outer": "^1", "shared": "^1"}})
        )
        (tmp_path / "bun.lock").write_text('{"packages": {}}')
        _node_package(
            tmp_path, "outer", "1.0.0", {"license": "MIT", "dependencies": {"shared": "^2"}}
        )
        _node_package(tmp_path, "shared", "1.0.0", {"license": "ISC"})
        _node_package(tmp_path / "node_modules" / "outer", "shared", "2.0.0", {"license": "0BSD"})

        components = inventory.node_components(inventory.Policy({}, {}), tmp_path)

        assert {(c.name, c.version): c.license for c in components} == {
            ("outer", "1.0.0"): "MIT",
            ("shared", "1.0.0"): "ISC",
            ("shared", "2.0.0"): "0BSD",
        }

    def test_a_platform_build_for_another_system_is_left_out(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"native": "^1"}}))
        (tmp_path / "bun.lock").write_text('{"packages": {}}')
        _node_package(
            tmp_path,
            "native",
            "1.0.0",
            {"license": "MIT", "optionalDependencies": {"native-darwin": "^1"}},
        )
        _node_package(tmp_path, "native-darwin", "1.0.0", {"license": "MIT", "os": ["darwin"]})

        components = inventory.node_components(inventory.Policy({}, {}), tmp_path)

        assert [c.name for c in components] == ["native"]

    def test_a_missing_production_dependency_is_an_error_not_an_omission(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"absent": "^1"}}))
        (tmp_path / "bun.lock").write_text('{"packages": {}}')

        with pytest.raises(inventory.MetadataUnavailableError, match="absent"):
            inventory.node_components(inventory.Policy({}, {}), tmp_path)

    def test_an_optional_dependency_not_installed_here_is_read_from_the_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"sharp": "^1"}}))
        (tmp_path / "bun.lock").write_text(
            '{"packages": {"lib-linux": ["lib-linux@1.2.4", "", {}, ""], "lib-win": ["lib-win@1.2.4", "", {}, ""]}}'
        )
        _node_package(
            tmp_path,
            "sharp",
            "1.0.0",
            {
                "license": "Apache-2.0",
                "optionalDependencies": {"lib-linux": "1.2.4", "lib-win": "1.2.4"},
            },
        )
        registry = {
            "https://registry.npmjs.org/lib-linux/1.2.4": {
                "license": "LGPL-3.0-or-later",
                "os": ["linux"],
                "cpu": ["x64"],
            },
            "https://registry.npmjs.org/lib-win/1.2.4": {"license": "MIT", "os": ["win32"]},
        }
        monkeypatch.setattr(inventory, "fetch_json", lambda url: registry[url])

        components = inventory.node_components(inventory.Policy({}, {}), tmp_path)

        assert {(c.name, c.version): c.license for c in components} == {
            ("sharp", "1.0.0"): "Apache-2.0",
            ("lib-linux", "1.2.4"): "LGPL-3.0-or-later",
        }


class TestPolicy:
    def test_overrides_and_reviews_are_keyed_by_ecosystem_and_name(self, tmp_path: Path) -> None:
        policy = tmp_path / "policy.toml"
        policy.write_text(
            '[overrides.python."odd-one"]\nlicense = "MIT"\nevidence = "its LICENSE file"\n\n'
            '[review.npm."lib"]\nlicense = "LGPL-3.0-or-later"\nstatus = "accepted"\n'
            'obligations = "text and source"\nfulfilled_by = "shipped"\n'
        )

        loaded = inventory.load_policy(policy)

        assert loaded.overrides == {"python:odd-one": inventory.Override("MIT", "its LICENSE file")}
        assert loaded.reviews["npm:lib"].status == "accepted"

    def test_a_notice_records_the_holder_and_the_evidence(self, tmp_path: Path) -> None:
        policy = tmp_path / "policy.toml"
        policy.write_text(
            '[notices.npm."anon"]\nholder = "Somebody"\nevidence = "the repository LICENSE"\n'
        )

        assert inventory.load_policy(policy).notices == {
            "npm:anon": inventory.Notice("Somebody", "the repository LICENSE")
        }

    def test_an_open_finding_without_an_issue_is_refused(self, tmp_path: Path) -> None:
        policy = tmp_path / "policy.toml"
        policy.write_text(
            '[review.python."x"]\nlicense = "AGPL-3.0-only"\nstatus = "open"\nobligations = "copyleft"\n'
        )

        with pytest.raises(ValueError, match="tracked_in"):
            inventory.load_policy(policy)

    def test_an_accepted_decision_has_to_say_how(self, tmp_path: Path) -> None:
        policy = tmp_path / "policy.toml"
        policy.write_text(
            '[review.python."x"]\nlicense = "MPL-2.0"\nstatus = "accepted"\nobligations = "source"\n'
        )

        with pytest.raises(ValueError, match="fulfilled_by"):
            inventory.load_policy(policy)

    def test_a_manual_component_states_its_status_and_obligation(self, tmp_path: Path) -> None:
        components = tmp_path / "components.toml"
        components.write_text(
            '[[component]]\nname = "redis"\nversion = "7"\nkind = "service image"\nlicense = "RSALv2"\n'
            'source = "https://redis.io"\nstatus = "open"\nobligations = "not OSI"\n'
        )

        with pytest.raises(ValueError, match="tracked_in"):
            inventory.load_manual_components(components)

        components.write_text(
            '[[component]]\nname = "redis"\nversion = "7"\nkind = "service image"\nlicense = "RSALv2"\n'
            'source = "https://redis.io"\nstatus = "deployment-review"\nobligations = "not OSI"\n'
        )
        assert inventory.load_manual_components(components)[0].status == "deployment-review"

    def test_the_committed_policy_loads(self) -> None:
        """The real file is data the check reads; a typo there is a red `security` job."""
        assert inventory.load_policy().reviews
        assert inventory.load_manual_components()


def _component(name: str, license: str | None, ecosystem: str = "python") -> object:
    return inventory.Component(
        ecosystem, name, "1.0", license, f"https://example.invalid/{name}", "test"
    )


class TestReview:
    def test_a_component_with_no_licence_is_a_problem_not_a_row(self) -> None:
        review = inventory.review_components(
            [_component("blank", None)], [], inventory.Policy({}, {})
        )

        assert len(review.problems) == 1
        assert "no readable licence metadata" in review.problems[0]
        assert 'overrides.python."blank"' in review.problems[0]

    def test_a_copyleft_component_without_a_decision_is_a_problem(self) -> None:
        review = inventory.review_components(
            [_component("lib", "LGPL-3.0-or-later")], [], inventory.Policy({}, {})
        )

        assert review.problems == [
            'python lib 1.0: LGPL-3.0-or-later needs a `[review.python."lib"]` decision'
        ]

    def test_an_unknown_identifier_is_a_problem_even_beside_mit(self) -> None:
        review = inventory.review_components(
            [_component("odd", "MIT AND Custom-1.0")], [], inventory.Policy({}, {})
        )

        assert len(review.problems) == 1
        assert "in no policy set" in review.problems[0]

    def test_a_decision_survives_only_for_the_licence_it_reviewed(self) -> None:
        decision = inventory.ReviewDecision("MPL-2.0", "accepted", "source", "shipped", "")
        policy = inventory.Policy({}, {"python:lib": decision})

        accepted = inventory.review_components([_component("lib", "MPL-2.0")], [], policy)
        changed = inventory.review_components([_component("lib", "AGPL-3.0-only")], [], policy)

        assert accepted.problems == []
        assert changed.problems == [
            "python lib 1.0: reviewed as MPL-2.0 but resolves to AGPL-3.0-only - review it again"
        ]

    def test_a_decision_about_a_component_that_is_gone_is_a_problem(self) -> None:
        decision = inventory.ReviewDecision("MPL-2.0", "accepted", "source", "shipped", "")
        policy = inventory.Policy(
            {"npm:old": inventory.Override("MIT", "x")}, {"python:gone": decision}
        )

        review = inventory.review_components([_component("kept", "MIT")], [], policy)

        assert review.problems == [
            "policy override for npm:old names a component the lockfiles no longer resolve - remove it",
            "policy review for python:gone names a component the lockfiles no longer resolve - remove it",
        ]

    def test_an_override_whose_component_now_declares_a_licence_is_stale(self) -> None:
        policy = inventory.Policy({"python:lib": inventory.Override("MIT", "read upstream")}, {})
        declared = inventory.Component(
            "python", "lib", "1.0", "MIT", "https://x", "License-Expression"
        )
        applied = inventory.Component(
            "python", "lib", "1.0", "MIT", "https://x", "override: read upstream"
        )

        assert inventory.review_components([applied], [], policy).problems == []
        problems = inventory.review_components([declared], [], policy).problems
        assert len(problems) == 1
        assert "the override in policy.toml is stale" in problems[0]

    def test_a_package_without_a_licence_file_needs_a_holder_and_a_text(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "MIT.txt").write_text("MIT")
        attributed = inventory.Component(
            "npm", "a", "1", "MIT", "https://x", "package.json license", False, "Ada"
        )
        anonymous = inventory.Component(
            "npm", "b", "1", "MIT", "https://x", "package.json license", False, ""
        )
        no_text = inventory.Component(
            "npm", "c", "1", "MIT AND ISC", "https://x", "package.json license", False, "Ada"
        )
        with_file = inventory.Component(
            "npm", "d", "1", "GPL-3.0-only", "https://x", "package.json license", True, ""
        )
        policy = inventory.Policy({}, {}, {"npm:b": inventory.Notice("Somebody", "found upstream")})

        assert (
            inventory.review_components([attributed, anonymous], [], policy, tmp_path).problems
            == []
        )
        anonymous_problems = inventory.review_components(
            [anonymous], [], inventory.Policy({}, {}), tmp_path
        ).problems
        assert anonymous_problems == [
            'npm b 1: ships no licence file and names no author - record `[notices.npm."b"]` with the copyright holder'
        ]
        text_problems = inventory.review_components(
            [no_text], [], inventory.Policy({}, {}), tmp_path
        ).problems
        assert text_problems == [
            f"npm c 1: ships no licence file and {tmp_path.name}/ISC.txt does not exist - add the text so the image can carry it"
        ]
        assert "text" not in " ".join(
            inventory.review_components(
                [with_file],
                [],
                inventory.Policy(
                    {},
                    {"npm:d": inventory.ReviewDecision("GPL-3.0-only", "accepted", "o", "f", "")},
                ),
                tmp_path,
            ).problems
        )

    def test_a_notice_for_a_package_that_ships_its_file_again_is_stale(
        self, tmp_path: Path
    ) -> None:
        policy = inventory.Policy({}, {}, {"npm:a": inventory.Notice("Somebody", "found upstream")})
        with_file = inventory.Component(
            "npm", "a", "1", "MIT", "https://x", "package.json license", True, ""
        )

        problems = inventory.review_components([with_file], [], policy, tmp_path).problems

        assert problems == [
            "policy notice for npm:a names a component that is gone or now ships its own licence file - remove it"
        ]

    def test_open_findings_are_counted_not_failed(self) -> None:
        decision = inventory.ReviewDecision(
            "AGPL-3.0-only", "open", "copyleft", "", "https://issues/1"
        )
        manual = inventory.ManualComponent(
            "redis", "7", "image", "RSALv2", "https://redis.io", "open", "n", "", "https://issues/2"
        )

        review = inventory.review_components(
            [_component("pdf", "AGPL-3.0-only")],
            [manual],
            inventory.Policy({}, {"python:pdf": decision}),
        )

        assert review.problems == []
        assert review.open_findings == [
            "pdf 1.0 (AGPL-3.0-only) - https://issues/1",
            "redis 7 - https://issues/2",
        ]


class TestNotices:
    def test_the_rendering_lists_findings_counts_and_every_row(self) -> None:
        decision = inventory.ReviewDecision("MPL-2.0", "accepted", "source", "shipped", "")
        manual = inventory.ManualComponent(
            "font", "v1", "font", "OFL-1.1", "https://fonts", "accepted", "text", "OFL.txt", ""
        )
        review = inventory.review_components(
            [_component("a", "MIT"), _component("b", "MPL-2.0"), _component("c", "MIT", "npm")],
            [manual],
            inventory.Policy({}, {"python:b": decision}),
        )

        rendered = inventory.render_notices(review)

        assert "## Open findings\n\nNone." in rendered
        assert "| MIT | 1 | 1 |" in rendered
        assert (
            "| b | 1.0 | MPL-2.0 | https://example.invalid/b | test; review accepted |" in rendered
        )
        assert (
            "| font | v1 | font | OFL-1.1 | https://fonts | accepted | text | OFL.txt |" in rendered
        )

    def test_a_package_without_a_licence_file_shows_whom_it_is_attributed_to(self) -> None:
        by_author = inventory.Component(
            "npm", "a", "1", "MIT", "https://x", "package.json license", False, "Ada"
        )
        by_policy = inventory.Component(
            "npm", "b", "1", "MIT", "https://x", "package.json license", False, ""
        )
        policy = inventory.Policy({}, {}, {"npm:b": inventory.Notice("Somebody", "found upstream")})

        rendered = inventory.render_notices(
            inventory.Review([by_author, by_policy], [], policy, [])
        )

        assert (
            "| a | 1 | MIT | https://x | package.json license; no licence file, attributed to Ada |"
            in rendered
        )
        assert (
            "| b | 1 | MIT | https://x | package.json license; no licence file, attributed to Somebody |"
            in rendered
        )

    def test_a_pipe_in_a_field_cannot_break_the_table(self) -> None:
        row = inventory.Component("python", "a|b", "1", "MIT", "https://x", "test")
        review = inventory.Review([row], [], inventory.Policy({}, {}), [])

        assert "| a\\|b | 1 | MIT |" in inventory.render_notices(review)


class TestMain:
    @pytest.fixture
    def notices(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "THIRD_PARTY_NOTICES.md"
        monkeypatch.setattr(inventory, "NOTICES_PATH", path)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        return path

    @staticmethod
    def _review(*components: object, problems: list[str] | None = None) -> object:
        return inventory.Review(list(components), [], inventory.Policy({}, {}), problems or [])

    def test_write_then_check_is_reviewed(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(inventory, "collect", lambda: self._review(_component("a", "MIT")))

        assert inventory.main(["write"]) == inventory.EXIT_REVIEWED
        assert notices.exists()
        assert inventory.main(["check"]) == inventory.EXIT_REVIEWED
        assert (
            capsys.readouterr().out.splitlines()[-1].startswith("LICENSES: REVIEWED - 1 components")
        )

    def test_stale_notices_fail_the_check(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        notices.write_text("something older")
        monkeypatch.setattr(inventory, "collect", lambda: self._review(_component("a", "MIT")))

        assert inventory.main(["check"]) == inventory.EXIT_FAILED
        out = capsys.readouterr().out.splitlines()
        assert "stale" in out[-1]
        assert "-something older" in out
        assert "+# Third-party notices" in out

    def test_a_difference_only_in_the_evidence_cell_is_not_stale(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two wheels of one release can read their licence from different places."""
        linux = inventory.Component(
            "python", "caio", "0.9.25", "Apache-2.0", "https://x", "License-Expression"
        )
        macos = inventory.Component(
            "python", "caio", "0.9.25", "Apache-2.0", "https://x", "licence file text"
        )
        notices.write_text(inventory.render_notices(self._review(macos)))
        monkeypatch.setattr(inventory, "collect", lambda: self._review(linux))

        assert inventory.main(["check"]) == inventory.EXIT_REVIEWED

    def test_a_different_licence_for_the_same_component_is_stale(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = inventory.Component(
            "python", "lib", "1.0", "MIT", "https://x", "License-Expression"
        )
        after = inventory.Component(
            "python", "lib", "1.0", "Apache-2.0", "https://x", "License-Expression"
        )
        notices.write_text(inventory.render_notices(self._review(before)))
        monkeypatch.setattr(inventory, "collect", lambda: self._review(after))

        assert inventory.main(["check"]) == inventory.EXIT_FAILED

    def test_an_untracked_finding_neither_writes_nor_passes(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            inventory,
            "collect",
            lambda: self._review(_component("x", None), problems=["x: no licence"]),
        )

        assert inventory.main(["write"]) == inventory.EXIT_FAILED
        assert not notices.exists()
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "x: no licence"
        assert out[-1] == "LICENSES: FAILED - 1 untracked finding(s); the notices were not written"

    def test_an_unreachable_index_is_a_failed_run_not_a_pass(
        self, notices: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def unreachable() -> object:
            raise inventory.MetadataUnavailableError("https://registry.npmjs.org/x/1: timed out")

        monkeypatch.setattr(inventory, "collect", unreachable)

        assert inventory.main(["check"]) == inventory.EXIT_FAILED
        assert "inventory did not complete" in capsys.readouterr().out.splitlines()[-1]

    def test_the_verdict_reaches_the_job_summary(
        self, notices: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        monkeypatch.setattr(inventory, "collect", lambda: self._review(_component("a", "MIT")))

        inventory.main(["write"])

        assert summary.read_text().startswith("LICENSES: REVIEWED")
