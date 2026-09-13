#!/usr/bin/env python3
"""Inventory every third-party component the images ship, and what licence it is under.

`THIRD_PARTY_NOTICES.md` is generated from this script and committed, so a release
carries the notices for exactly the components its lockfiles resolve to. The
review of what those licences oblige and how each obligation is met is prose, in
`docs/licenses.md`; this script is the evidence that prose stands on.

Three decisions shape it:

**The inventory is what a deployment installs, not what a laptop has.** The
backend set is `uv export --frozen --no-dev`, with environment markers evaluated
for Linux, because that is what `backend/Dockerfile` runs; the frontend set is
the production closure of `frontend/package.json`, with platform-specific optional
packages kept only when they build for Linux. A package this machine does not
have installed - `jeepney` on macOS, `@img/sharp-libvips-linux-x64` on anything
but Linux - has its metadata read from the package index instead, and a lookup
that fails is a failure of the run, never an omission from the notices.

**A scanner's "unknown" is a question, not an answer.** A component whose
metadata names no licence, or names one this script has no policy for, fails
`check` until a person records what they found in `licenses/policy.toml`, with
the evidence they read. The same file holds the review decisions: any component
under a licence in `REVIEW_FAMILIES` needs an entry saying whether the
obligations are met or the finding is open and where it is tracked. An entry
also records the licence it reviewed, so a dependency that changes licence on
upgrade reopens the question instead of inheriting the old answer.

**Components no lockfile knows are recorded by hand.** Runtime images, the
Debian packages the backend image installs, the vendored fonts and the brand
glyphs live in `licenses/components.toml`, each with a status and the obligation
it carries. The script validates that file and renders it into the notices
beside the generated rows, so the one document covers the whole image.

Usage::

    make licenses          # regenerate THIRD_PARTY_NOTICES.md
    make licenses-check    # CI: stale notices or an untracked finding exit 1

The last line of output is always `LICENSES: <STATE> - <detail>`, `STATE` one of
`REVIEWED` or `FAILED`, for the same reason `scripts/audit_dependencies.py` has
one: `make` folds every failing exit code into its own 2, so a job reading this
through a make target can only read the line. Open findings that are tracked do
not fail the run - the review is honest about them - but they are counted in the
verdict and listed in the notices.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Literal

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
POLICY_PATH = REPO_ROOT / "licenses" / "policy.toml"
COMPONENTS_PATH = REPO_ROOT / "licenses" / "components.toml"
NOTICES_PATH = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
# The licence texts `frontend/scripts/collect-licenses.ts` places beside a package
# that publishes none of its own, one file per SPDX identifier.
TEXTS_DIR = FRONTEND_DIR / "licenses" / "texts"

VERDICT_PREFIX = "LICENSES:"
EXIT_REVIEWED = 0
EXIT_FAILED = 1

# The two architectures `images.yml` builds for, as npm spells them: `oven/bun:1`
# is Debian glibc on x64 and arm64. A platform package is in the frontend image
# when its `os`, `cpu` and `libc` fields all admit one of these.
IMAGE_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("linux", "x64", "glibc"),
    ("linux", "arm64", "glibc"),
)

# The same two, as Python markers see them. A marker is evaluated once per
# environment and a requirement true in either is in the inventory.
LINUX_ENVIRONMENTS: tuple[dict[str, str], ...] = tuple(
    {
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
        "platform_machine": machine,
        "python_version": "3.12",
        "python_full_version": "3.12.0",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    }
    for machine in ("x86_64", "aarch64")
)

# Licences whose obligations the notices file and the packages' own licence files
# meet without a per-component decision: attribution and a copy of the text.
PERMISSIVE_LICENSES = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BlueOak-1.0.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "CNRI-Python",
        "ISC",
        "MIT",
        "MIT-0",
        "MIT-CMU",
        "PSF-2.0",
        "Python-2.0",
        "Unlicense",
        "Zlib",
    }
)

# Licences that carry an obligation beyond attribution - copyleft of some
# strength, a share-alike clause, or terms that are not open source at all. A
# component under one of these needs a `[review.<ecosystem>."<name>"]` entry in
# the policy saying how the obligation is met, or that it is not yet and where
# that is tracked.
REVIEW_FAMILIES = frozenset(
    {
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "Artistic-1.0-Perl",
        "Artistic-2.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "CDDL-1.0",
        "EPL-1.0",
        "EPL-2.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MPL-2.0",
        "OFL-1.1",
        "SSPL-1.0",
    }
)

# Free-text `License` fields that name a permissive licence without using its SPDX
# id. Only unambiguous spellings: a bare "BSD" is not here because BSD-2-Clause and
# BSD-3-Clause differ in an obligation, and the licence file decides which.
LICENSE_FIELD_ALIASES: dict[str, str] = {
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache2.0": "Apache-2.0",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "modified bsd license": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "isc": "ISC",
    "isc license": "ISC",
    "mit": "MIT",
    "mit license": "MIT",
    "mpl-2.0": "MPL-2.0",
    "psf-2.0": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "unlicense": "Unlicense",
    "the unlicense": "Unlicense",
}

# Trove classifiers that name one licence. `BSD License` and the bare LGPL and GPL
# classifiers are deliberately absent for the same reason as above. Classifiers
# decide only when every licence classifier a distribution carries is in this
# table and they all name the same licence: `text-unidecode` lists Artistic, GPL
# and GPLv2+, and reading the one recognised entry as the answer would turn a
# dual licence into a copyleft one.
CLASSIFIER_LICENSES: dict[str, str] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1-or-later",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
}

LICENSE_FILE_NAMES = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)

Ecosystem = Literal["python", "npm"]
Standing = Literal["permissive", "review", "unknown"]


class MetadataUnavailableError(Exception):
    """A component's metadata could not be read locally or from its index.

    Raised rather than recorded as "unknown", because an unreachable index is a
    property of this run and not of the component; the notices must not be
    regenerated from it and the check must not pass on it.
    """


@dataclass(frozen=True)
class Component:
    """One distributed third-party package, as the notices describe it.

    `license` is an SPDX expression, or None when nothing readable names one.
    `evidence` says where the expression came from - a `License-Expression`
    header, a classifier, the licence file's text, the package index, or an
    override a person recorded - so a reader of the notices can tell a declared
    licence from an inferred one.
    """

    ecosystem: Ecosystem
    name: str
    version: str
    license: str | None
    source: str
    evidence: str
    # Whether the package itself ships a licence file. None when it was not
    # inspected: a distribution read from an index rather than from disk.
    license_file: bool | None = None
    # Whom the package's own metadata names as its author, for one that ships
    # no licence file and so no copyright notice of its own.
    attribution: str = ""

    @property
    def key(self) -> str:
        return f"{self.ecosystem}:{self.name}"


@dataclass(frozen=True)
class ReviewDecision:
    """A recorded answer for a component under a licence in `REVIEW_FAMILIES`."""

    license: str
    status: Literal["accepted", "open"]
    obligations: str
    fulfilled_by: str
    tracked_in: str


@dataclass(frozen=True)
class Override:
    """A licence a person determined for a component whose metadata does not say."""

    license: str
    evidence: str


@dataclass(frozen=True)
class Notice:
    """The copyright holder a person found for a package that names none itself."""

    holder: str
    evidence: str


@dataclass(frozen=True)
class Policy:
    overrides: Mapping[str, Override]
    reviews: Mapping[str, ReviewDecision]
    notices: Mapping[str, Notice] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualComponent:
    """A component no lockfile knows about, recorded in `licenses/components.toml`.

    `license` is free text rather than an SPDX expression on purpose: a Debian
    base image is hundreds of packages under dozens of licences, and pretending
    that is one identifier would be the blanket claim the review exists to avoid.
    """

    name: str
    version: str
    kind: str
    license: str
    source: str
    status: Literal["accepted", "open", "deployment-review"]
    obligations: str
    fulfilled_by: str
    tracked_in: str


def classify_expression(expression: str) -> Standing:
    """The strictest obligation an SPDX expression can impose, given the two sets above.

    `OR` lets the distributor choose, so the most permissive alternative counts;
    `AND` binds every term, so the most demanding one does. A `WITH` exception is
    read as the base licence - the exception only ever narrows an obligation -
    and the review entry records what the exception actually grants. An
    identifier in neither set is unknown, and unknown wins over everything:
    nothing about a licence this script has no policy for can be assumed.
    """
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    position = 0
    malformed = False

    def parse_or() -> Standing:
        nonlocal position
        standings = [parse_and()]
        while position < len(tokens) and tokens[position].upper() == "OR":
            position += 1
            standings.append(parse_and())
        if "permissive" in standings:
            return "permissive"
        if "review" in standings:
            return "review"
        return "unknown"

    def parse_and() -> Standing:
        nonlocal position
        standings = [parse_term()]
        while position < len(tokens) and tokens[position].upper() == "AND":
            position += 1
            standings.append(parse_term())
        if "unknown" in standings:
            return "unknown"
        if "review" in standings:
            return "review"
        return "permissive"

    def parse_term() -> Standing:
        nonlocal position, malformed
        if position >= len(tokens):
            malformed = True
            return "unknown"
        token = tokens[position]
        position += 1
        if token == "(":
            inner = parse_or()
            if position < len(tokens) and tokens[position] == ")":
                position += 1
                return inner
            malformed = True
            return "unknown"
        if token == ")":
            malformed = True
            return "unknown"
        if position + 1 < len(tokens) and tokens[position].upper() == "WITH":
            position += 2
        return classify_identifier(token)

    standing = parse_or()
    if malformed or position != len(tokens):
        return "unknown"
    return standing


def classify_identifier(identifier: str) -> Standing:
    if identifier in PERMISSIVE_LICENSES:
        return "permissive"
    if identifier in REVIEW_FAMILIES:
        return "review"
    return "unknown"


def license_from_text(text: str) -> str | None:
    """Name the licence a licence file's text is a copy of, or None if unsure.

    Only the families whose wording is distinctive enough to read from a file are
    recognised; the BSD variants are told apart by the third clause, and ISC from
    0BSD by whether the notice has to be reproduced. Anything else is a question
    for a person, which is what returning None turns it into.
    """
    flat = " ".join(text.split())
    lowered = flat.lower()
    if "gnu affero general public license" in lowered or "gnu affero gpl" in lowered:
        return "AGPL-3.0-only"
    if "gnu lesser general public license" in lowered:
        later = "any later version" in lowered
        if "version 2.1" in lowered:
            return "LGPL-2.1-or-later" if later else "LGPL-2.1-only"
        return "LGPL-3.0-or-later" if later else "LGPL-3.0-only"
    if "gnu general public license" in lowered:
        later = "any later version" in lowered
        if "version 2" in lowered:
            return "GPL-2.0-or-later" if later else "GPL-2.0-only"
        return "GPL-3.0-or-later" if later else "GPL-3.0-only"
    if "mozilla public license" in lowered and "2.0" in lowered:
        return "MPL-2.0"
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in lowered:
        return "MIT"
    if (
        "permission to use, copy, modify, and/or distribute this software for any purpose"
        in lowered
    ):
        return "ISC" if "provided that the above copyright notice" in lowered else "0BSD"
    if "redistribution and use in source and binary forms" in lowered:
        third_clause = (
            "neither the name" in lowered or "may not be used to endorse or promote" in lowered
        )
        return "BSD-3-Clause" if third_clause else "BSD-2-Clause"
    if "this is free and unencumbered software released into the public domain" in lowered:
        return "Unlicense"
    if "python software foundation license version 2" in lowered:
        return "PSF-2.0"
    return None


def fetch_json(url: str, attempts: int = 3, timeout: float = 20.0) -> dict[str, object]:
    """One index document, retried, because a slow answer is not information about a package."""
    failure: Exception | None = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - https index URLs only
                loaded: dict[str, object] = json.load(response)
                return loaded
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            failure = error
    raise MetadataUnavailableError(f"{url}: {failure}")


def as_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def runtime_requirements(backend_dir: Path = BACKEND_DIR) -> dict[str, str]:
    """Name to version for everything the backend image installs, on Linux.

    `uv export --no-dev` is the lock resolved to what `uv sync --frozen --no-dev`
    in the Dockerfile installs, markers included; a requirement whose marker is
    false on both image architectures is not in the image and not in the notices.
    """
    export = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--quiet"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    versions: dict[str, str] = {}
    for line in export.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        requirement = Requirement(stripped)
        if requirement.marker is not None and not any(
            requirement.marker.evaluate(environment) for environment in LINUX_ENVIRONMENTS
        ):
            continue
        pinned = [spec.version for spec in requirement.specifier if spec.operator == "=="]
        if len(pinned) != 1:
            raise ValueError(f"`uv export` line is not pinned to one version: {stripped}")
        versions[canonical_python_name(requirement.name)] = pinned[0]
    return versions


def canonical_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def first_project_url(urls: Iterable[str], fallback: str) -> str:
    """The most source-like of a distribution's `Project-URL`s, or the fallback.

    Preference order is the label, so the result does not depend on the order the
    packager listed them in; the notices are diffed, and a table that reorders
    itself on a re-run is a stale check that never settles.
    """
    labelled: dict[str, str] = {}
    for entry in urls:
        label, _, url = entry.partition(",")
        labelled.setdefault(label.strip().lower(), url.strip())
    for label in (
        "source",
        "source code",
        "repository",
        "homepage",
        "home",
        "github",
        "documentation",
    ):
        if labelled.get(label):
            return labelled[label]
    return fallback


def python_component(name: str, version: str, policy: Policy) -> Component:
    """One backend distribution, from the local environment or from PyPI."""
    key = f"python:{name}"
    fallback_source = f"https://pypi.org/project/{name}/{version}/"
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        distribution = None

    if distribution is not None and distribution.version == version:
        meta = distribution.metadata
        expression = as_str(meta.get("License-Expression"))
        license_field = as_str(meta.get("License"))
        classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
        project_urls = list(meta.get_all("Project-URL") or [])
        home_page = as_str(meta.get("Home-page"))
        license_texts = [
            path.locate().read_text(errors="replace")
            for path in (distribution.files or [])
            if LICENSE_FILE_NAMES.match(path.name)
        ]
        attribution = people(
            meta.get("Author"),
            meta.get("Author-email"),
            meta.get("Maintainer"),
            meta.get("Maintainer-email"),
        )
    else:
        document = fetch_json(f"https://pypi.org/pypi/{name}/{version}/json")
        info = document.get("info")
        info = info if isinstance(info, dict) else {}
        expression = as_str(info.get("license_expression"))
        license_field = as_str(info.get("license"))
        classifiers = [
            c for c in as_str_list(info.get("classifiers")) if c.startswith("License ::")
        ]
        raw_urls = info.get("project_urls")
        project_urls = (
            [f"{k}, {v}" for k, v in raw_urls.items()] if isinstance(raw_urls, dict) else []
        )
        home_page = as_str(info.get("home_page"))
        license_texts = []
        attribution = people(
            info.get("author"),
            info.get("author_email"),
            info.get("maintainer"),
            info.get("maintainer_email"),
        )

    source = first_project_url(project_urls, home_page or fallback_source)
    resolved, evidence = python_license(expression, license_field, classifiers, license_texts)
    resolved, evidence = apply_override(policy, key, resolved, evidence)
    license_file = bool(license_texts) if distribution is not None else None
    return Component("python", name, version, resolved, source, evidence, license_file, attribution)


def people(*fields: object) -> str:
    """The names in a distribution's author and maintainer fields, as one line.

    `Author-email` often carries the name too (`Name <address>`), and a wheel built
    from a `pyproject.toml` with only `authors = [{name, email}]` puts everything
    there and leaves `Author` empty, so both are read; the address itself is not
    an attribution and is dropped.
    """
    names: list[str] = []
    for value in fields:
        for entry in as_str(value).split(","):
            name = re.sub(r"<[^>]*>", "", entry).strip().strip('"')
            if name and "@" not in name and name not in names:
                names.append(name)
    return ", ".join(names)


def python_license(
    expression: str, license_field: str, classifiers: list[str], license_texts: list[str]
) -> tuple[str | None, str]:
    """A distribution's licence from its own metadata, most authoritative source first."""
    if expression:
        return expression, "License-Expression"
    alias = LICENSE_FIELD_ALIASES.get(license_field.lower()) or LICENSE_FIELD_ALIASES.get(
        license_field.splitlines()[0].strip().lower() if license_field else ""
    )
    if alias:
        return alias, "License field"
    named = {CLASSIFIER_LICENSES.get(c) for c in classifiers}
    if len(named) == 1 and None not in named:
        return next(iter(named)), "classifier"
    for text in license_texts:
        recognised = license_from_text(text)
        if recognised:
            return recognised, "licence file text"
    return None, "no readable licence metadata"


def apply_override(
    policy: Policy, key: str, resolved: str | None, evidence: str
) -> tuple[str | None, str]:
    """An override answers only the question the metadata could not.

    Applied when nothing readable names a licence, and only then: once a release
    starts declaring one, the metadata wins and `review_components` reports the
    override as stale, so a licence that changed under an override reopens the
    question instead of inheriting the old answer.
    """
    override = policy.overrides.get(key)
    if override is not None and resolved is None:
        return override.license, f"override: {override.evidence}"
    return resolved, evidence


def python_components(policy: Policy, backend_dir: Path = BACKEND_DIR) -> list[Component]:
    return [
        python_component(name, version, policy)
        for name, version in sorted(runtime_requirements(backend_dir).items())
    ]


def read_package_json(path: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(path.read_text())
    return loaded


def resolve_node_package(name: str, from_dir: Path, root: Path) -> Path | None:
    """`node_modules/<name>/package.json`, looked up the way `require` does.

    A nested `node_modules` holds the version a dependant needed when the hoisted
    one did not satisfy it, so the walk starts beside the dependant and climbs to
    the project root - the closest match is the one that package actually loads.
    """
    directory = from_dir
    while True:
        candidate = directory / "node_modules" / name / "package.json"
        if candidate.is_file():
            return candidate
        if directory == root:
            return None
        directory = directory.parent


def builds_for_linux(manifest: Mapping[str, object]) -> bool:
    """Whether a platform-specific package is one the frontend image can contain.

    A package whose `os`, `cpu` or `libc` field rules out both image targets - a
    Windows or musl build, a s390x one - is not in the image whatever the lockfile
    resolved. Each field is read with npm's own semantics: an absent field admits
    everything, a listed value is an allowlist, and a `!value` excludes without
    listing, so `["!darwin"]` admits both targets and `["!linux"]` neither.
    """
    fields = (
        as_str_list(manifest.get("os")),
        as_str_list(manifest.get("cpu")),
        as_str_list(manifest.get("libc")),
    )
    return any(
        all(admits(values, wanted) for values, wanted in zip(fields, target, strict=True))
        for target in IMAGE_TARGETS
    )


def admits(values: list[str], candidate: str) -> bool:
    positives = [value for value in values if not value.startswith("!")]
    negatives = {value[1:] for value in values if value.startswith("!")}
    return (not positives or candidate in positives) and candidate not in negatives


def lockfile_versions(lockfile: Path) -> dict[str, set[str]]:
    """Every version of every package `bun.lock` resolved, for the ones not installed here.

    The lockfile is JSON with trailing commas, hence the substitution before
    parsing. Each entry's first element is `name@version`; a nested entry is keyed
    `dependant/name` and still names the package it is a copy of.
    """
    text = re.sub(r",(\s*[}\]])", r"\1", lockfile.read_text())
    loaded: dict[str, object] = json.loads(text)
    packages = loaded.get("packages")
    versions: dict[str, set[str]] = {}
    if not isinstance(packages, dict):
        return versions
    for entry in packages.values():
        if not isinstance(entry, list) or not entry or not isinstance(entry[0], str):
            continue
        name, _, version = entry[0].rpartition("@")
        if name and version:
            versions.setdefault(name, set()).add(version)
    return versions


def node_license(
    manifest: Mapping[str, object], license_texts: Iterable[str]
) -> tuple[str | None, str]:
    """An npm manifest's licence as an SPDX expression, and where it was read from.

    `license` is the modern field and is usually already an expression, sometimes
    wrapped in one pair of parentheses; `licenses` is the pre-2014 array form. A
    `SEE LICENSE IN <file>` marker or a missing field sends the question to the
    licence file, and `UNLICENSED` is a refusal, not a licence.
    """
    field = manifest.get("license")
    if isinstance(field, dict):
        field = field.get("type")
    if isinstance(field, str):
        declared = field.strip()
        if declared.startswith("(") and declared.endswith(")"):
            declared = declared[1:-1].strip()
        if (
            declared
            and declared.upper() != "UNLICENSED"
            and not declared.upper().startswith("SEE LICENSE IN")
        ):
            return declared, "package.json license"
    legacy = manifest.get("licenses")
    if isinstance(legacy, list):
        types = [item.get("type") if isinstance(item, dict) else item for item in legacy]
        names = [t.strip() for t in types if isinstance(t, str) and t.strip()]
        if names:
            return " OR ".join(names), "package.json licenses"
    for text in license_texts:
        recognised = license_from_text(text)
        if recognised:
            return recognised, "licence file text"
    return None, "no readable licence metadata"


def manifest_attribution(manifest: Mapping[str, object]) -> str:
    """Whom an npm manifest names: `author`, else its `contributors`, as one line."""
    people: list[str] = []
    contributors = manifest.get("contributors")
    for entry in [
        manifest.get("author"),
        *(contributors if isinstance(contributors, list) else []),
    ]:
        if isinstance(entry, str) and entry.strip():
            people.append(entry.strip())
        elif isinstance(entry, dict) and as_str(entry.get("name")):
            people.append(as_str(entry.get("name")))
    return ", ".join(people)


def node_source(manifest: Mapping[str, object], name: str, version: str) -> str:
    repository = manifest.get("repository")
    url = repository.get("url") if isinstance(repository, dict) else repository
    if isinstance(url, str) and url.strip():
        cleaned = url.strip().removeprefix("git+").removesuffix(".git")
        cleaned = re.sub(r"^git://", "https://", cleaned)
        cleaned = re.sub(r"^(ssh://)?git@github\.com[:/]", "https://github.com/", cleaned)
        if re.match(r"^[\w.-]+/[\w.-]+$", cleaned):
            cleaned = f"https://github.com/{cleaned}"
        return cleaned
    homepage = as_str(manifest.get("homepage"))
    return homepage or f"https://www.npmjs.com/package/{name}/v/{version}"


def node_components(policy: Policy, frontend_dir: Path = FRONTEND_DIR) -> list[Component]:
    """The production closure of `frontend/package.json`, as the image ships it.

    Dependencies and optional dependencies are followed; peer dependencies too,
    when installed, because bun installs them and the standalone build traces
    whatever it imports. An optional dependency that is not installed here is a
    platform build for another system: its manifest comes from the npm registry
    and it is kept only when it builds for Linux. Anything else missing is an
    error, because a missing production dependency means `node_modules` is not
    the lockfile's, and an inventory of it would be an inventory of something else.
    """
    root_manifest = read_package_json(frontend_dir / "package.json")
    locked = lockfile_versions(frontend_dir / "bun.lock")
    pending: list[tuple[str, Path, bool]] = [
        (name, frontend_dir, False)
        for name in sorted(dependencies_of(root_manifest, optional=False))
    ]
    pending += [
        (name, frontend_dir, True) for name in sorted(dependencies_of(root_manifest, optional=True))
    ]
    seen: set[tuple[str, str]] = set()
    components: list[Component] = []

    while pending:
        name, from_dir, optional = pending.pop()
        manifest_path = resolve_node_package(name, from_dir, frontend_dir)
        if manifest_path is None:
            if not optional:
                raise MetadataUnavailableError(
                    f"{name} is a production dependency and is not installed under {frontend_dir}"
                )
            for version in sorted(locked.get(name, set())):
                if (name, version) in seen:
                    continue
                seen.add((name, version))
                manifest = fetch_json(f"https://registry.npmjs.org/{name}/{version}")
                if builds_for_linux(manifest):
                    components.append(node_component(policy, manifest, name, version, None))
            continue

        manifest = read_package_json(manifest_path)
        version = as_str(manifest.get("version"))
        if (name, version) in seen:
            continue
        seen.add((name, version))
        if not builds_for_linux(manifest):
            continue
        package_dir = manifest_path.parent
        texts = [
            path.read_text(errors="replace")
            for path in sorted(package_dir.iterdir())
            if path.is_file() and LICENSE_FILE_NAMES.match(path.name)
        ]
        components.append(node_component(policy, manifest, name, version, texts))
        pending += [(dep, package_dir, False) for dep in dependencies_of(manifest, optional=False)]
        pending += [(dep, package_dir, True) for dep in dependencies_of(manifest, optional=True)]
        peers = manifest.get("peerDependencies")
        if isinstance(peers, dict):
            pending += [
                (peer, package_dir, True)
                for peer in sorted(peers)
                if resolve_node_package(peer, package_dir, frontend_dir) is not None
            ]

    return sorted(components, key=lambda component: (component.name, component.version))


def dependencies_of(manifest: Mapping[str, object], *, optional: bool) -> list[str]:
    field = manifest.get("optionalDependencies" if optional else "dependencies")
    return sorted(field.keys()) if isinstance(field, dict) else []


def node_component(
    policy: Policy,
    manifest: Mapping[str, object],
    name: str,
    version: str,
    texts: list[str] | None,
) -> Component:
    """One npm package; `texts` is None when it was read from the registry, not from disk."""
    source = node_source(manifest, name, version)
    expression, evidence = node_license(manifest, texts or [])
    expression, evidence = apply_override(policy, f"npm:{name}", expression, evidence)
    license_file = bool(texts) if texts is not None else None
    return Component(
        "npm",
        name,
        version,
        expression,
        source,
        evidence,
        license_file,
        manifest_attribution(manifest),
    )


def load_policy(path: Path = POLICY_PATH) -> Policy:
    """`licenses/policy.toml`: overrides and review decisions, keyed `ecosystem:name`."""
    document = tomllib.loads(path.read_text()) if path.exists() else {}
    overrides: dict[str, Override] = {}
    reviews: dict[str, ReviewDecision] = {}
    notices: dict[str, Notice] = {}
    for ecosystem in ("python", "npm"):
        for name, entry in dict_section(document, "overrides", ecosystem).items():
            overrides[f"{ecosystem}:{name}"] = Override(
                license=required_str(entry, "license", f"overrides.{ecosystem}.{name}"),
                evidence=required_str(entry, "evidence", f"overrides.{ecosystem}.{name}"),
            )
        for name, entry in dict_section(document, "notices", ecosystem).items():
            notices[f"{ecosystem}:{name}"] = Notice(
                holder=required_str(entry, "holder", f"notices.{ecosystem}.{name}"),
                evidence=required_str(entry, "evidence", f"notices.{ecosystem}.{name}"),
            )
        for name, entry in dict_section(document, "review", ecosystem).items():
            where = f"review.{ecosystem}.{name}"
            status = required_str(entry, "status", where)
            if status not in ("accepted", "open"):
                raise ValueError(f"{where}: status must be `accepted` or `open`, not {status!r}")
            tracked_in = as_str(entry.get("tracked_in"))
            if status == "open" and not tracked_in:
                raise ValueError(f"{where}: an open finding needs `tracked_in` - an issue URL")
            reviews[f"{ecosystem}:{name}"] = ReviewDecision(
                license=required_str(entry, "license", where),
                status=status,
                obligations=required_str(entry, "obligations", where),
                fulfilled_by=required_str(entry, "fulfilled_by", where)
                if status == "accepted"
                else as_str(entry.get("fulfilled_by")),
                tracked_in=tracked_in,
            )
    return Policy(overrides=overrides, reviews=reviews, notices=notices)


def dict_section(document: Mapping[str, object], *keys: str) -> dict[str, Mapping[str, object]]:
    node: object = document
    for key in keys:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    if not isinstance(node, dict):
        return {}
    return {name: entry for name, entry in node.items() if isinstance(entry, dict)}


def required_str(entry: Mapping[str, object], key: str, where: str) -> str:
    value = as_str(entry.get(key))
    if not value:
        raise ValueError(f"{where}: `{key}` is required")
    return value


def load_manual_components(path: Path = COMPONENTS_PATH) -> list[ManualComponent]:
    """`licenses/components.toml`, validated: every row states its status and its obligation."""
    document = tomllib.loads(path.read_text()) if path.exists() else {}
    rows = document.get("component")
    if not isinstance(rows, list):
        return []
    components: list[ManualComponent] = []
    for index, entry in enumerate(rows):
        if not isinstance(entry, dict):
            raise TypeError(f"components.toml: entry {index} is not a table")
        where = f"component[{index}] ({as_str(entry.get('name')) or 'unnamed'})"
        status = required_str(entry, "status", where)
        if status not in ("accepted", "open", "deployment-review"):
            raise ValueError(
                f"{where}: status must be `accepted`, `open` or `deployment-review`, not {status!r}"
            )
        tracked_in = as_str(entry.get("tracked_in"))
        if status == "open" and not tracked_in:
            raise ValueError(f"{where}: an open finding needs `tracked_in` - an issue URL")
        components.append(
            ManualComponent(
                name=required_str(entry, "name", where),
                version=required_str(entry, "version", where),
                kind=required_str(entry, "kind", where),
                license=required_str(entry, "license", where),
                source=required_str(entry, "source", where),
                status=status,
                obligations=required_str(entry, "obligations", where),
                fulfilled_by=required_str(entry, "fulfilled_by", where)
                if status == "accepted"
                else as_str(entry.get("fulfilled_by")),
                tracked_in=tracked_in,
            )
        )
    return components


@dataclass(frozen=True)
class Review:
    """Everything the notices render and the check judges, computed once."""

    components: list[Component]
    manual: list[ManualComponent]
    policy: Policy
    problems: list[str]

    @property
    def open_findings(self) -> list[str]:
        findings = [
            f"{component.name} {component.version} ({component.license}) - {decision.tracked_in}"
            for component in self.components
            if (decision := self.policy.reviews.get(component.key)) is not None
            and decision.status == "open"
        ]
        findings += [
            f"{row.name} {row.version} - {row.tracked_in or row.status}"
            for row in self.manual
            if row.status != "accepted"
        ]
        return findings


def review_components(
    components: list[Component],
    manual: list[ManualComponent],
    policy: Policy,
    texts_dir: Path = TEXTS_DIR,
) -> Review:
    """Judge the inventory against the policy; every problem is one a person has to answer."""
    problems: list[str] = []
    present = {component.key for component in components}
    # A notice is stale for a component that is gone or is known to ship its own
    # licence file. One read from an index (`license_file` None) was not inspected
    # on this machine - a Linux-only build on a macOS laptop - and keeps its notice.
    with_file = {c.key for c in components if c.license_file is True}
    for component in components:
        label = f"{component.ecosystem} {component.name} {component.version}"
        if component.key in policy.overrides and not component.evidence.startswith("override:"):
            problems.append(
                f"{label}: its metadata now names {component.license!r} ({component.evidence}); "
                f"the override in policy.toml is stale - remove it, or review the new licence"
            )
        if component.license_file is False and component.license is not None:
            problems += missing_notice_problems(component, label, policy, texts_dir)
        if component.license is None:
            problems.append(
                f'{label}: no readable licence metadata - record `[overrides.{component.ecosystem}."{component.name}"]` with evidence'
            )
            continue
        standing = classify_expression(component.license)
        decision = policy.reviews.get(component.key)
        if standing == "unknown":
            problems.append(
                f"{label}: licence {component.license!r} is in no policy set - classify it, or override it with evidence"
            )
        elif standing == "review" and decision is None:
            problems.append(
                f'{label}: {component.license} needs a `[review.{component.ecosystem}."{component.name}"]` decision'
            )
        if decision is not None and decision.license != component.license:
            problems.append(
                f"{label}: reviewed as {decision.license} but resolves to {component.license} - review it again"
            )
    for key in sorted(set(policy.overrides) - present):
        problems.append(
            f"policy override for {key} names a component the lockfiles no longer resolve - remove it"
        )
    for key in sorted(set(policy.reviews) - present):
        problems.append(
            f"policy review for {key} names a component the lockfiles no longer resolve - remove it"
        )
    for key in sorted(key for key in policy.notices if key not in present or key in with_file):
        problems.append(
            f"policy notice for {key} names a component that is gone or now ships its own licence file - remove it"
        )
    return Review(components=components, manual=manual, policy=policy, problems=problems)


def missing_notice_problems(
    component: Component, label: str, policy: Policy, texts_dir: Path
) -> list[str]:
    """What a package that publishes no licence file still owes its recipients.

    An image cannot copy a file that does not exist. The frontend image writes a
    NOTICE from the manifest and places the licence text from
    `frontend/licenses/texts/` beside such a package; the backend image carries the
    same texts under `/app/licenses/texts/` and each wheel's own `METADATA`, which
    names its author. Both need somebody to attribute - the metadata's author, or
    a holder a person recorded in the policy - and a text for every identifier in
    the expression.
    """
    problems: list[str] = []
    if not component.attribution and component.key not in policy.notices:
        problems.append(
            f'{label}: ships no licence file and names no author - record `[notices.{component.ecosystem}."{component.name}"]` with the copyright holder'
        )
    assert component.license is not None
    for identifier in spdx_identifiers(component.license):
        if not (texts_dir / f"{identifier}.txt").is_file():
            problems.append(
                f"{label}: ships no licence file and {texts_dir.name}/{identifier}.txt does not exist - add the text so the image can carry it"
            )
    return problems


def spdx_identifiers(expression: str) -> list[str]:
    """The licence identifiers in an expression, without operators, exceptions or parentheses."""
    identifiers: list[str] = []
    tokens = re.findall(r"[^\s()]+", expression)
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.upper() == "WITH":
            skip_next = True
            continue
        if token.upper() in ("AND", "OR"):
            continue
        if token not in identifiers:
            identifiers.append(token)
    return identifiers


def collect(backend_dir: Path = BACKEND_DIR, frontend_dir: Path = FRONTEND_DIR) -> Review:
    policy = load_policy()
    manual = load_manual_components()
    components = python_components(policy, backend_dir) + node_components(policy, frontend_dir)
    return review_components(components, manual, policy)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_notices(review: Review) -> str:
    """The committed document: one table per ecosystem, the hand-recorded rows, the findings."""
    lines: list[str] = [
        "# Third-party notices",
        "",
        "AgenticOS is licensed under the Apache License 2.0 (`LICENSE`, `NOTICE`). The",
        "images it publishes also carry the components below, each under its own licence.",
        "",
        "This file is generated by `scripts/license_inventory.py` from `backend/uv.lock`",
        "and `frontend/bun.lock`; do not edit it by hand. `make licenses` regenerates it",
        "and `make licenses-check` fails when it is stale. What these licences oblige and",
        "how each obligation is met is reviewed in `docs/licenses.md`.",
        "",
        "Each component's own licence file, with its copyright notice, ships beside it:",
        "the backend image keeps every wheel's `*.dist-info/` and the frontend image",
        "collects every package's licence file under `/app/licenses/`. A package that",
        "publishes none gets a NOTICE there naming its licence and author, with the",
        "licence text from `frontend/licenses/texts/`; the holder recorded for one that",
        "names no author is in the evidence column below.",
        "",
    ]
    findings = review.open_findings
    lines += ["## Open findings", ""]
    if findings:
        lines += [f"- {cell(finding)}" for finding in findings]
    else:
        lines.append("None.")
    lines.append("")

    counts: dict[str, dict[Ecosystem, int]] = {}
    for component in review.components:
        counts.setdefault(component.license or "", {"python": 0, "npm": 0})[
            component.ecosystem
        ] += 1
    lines += ["## Licences", "", "| Licence | Backend | Frontend |", "|---|---:|---:|"]
    for expression in sorted(counts, key=lambda e: (-(counts[e]["python"] + counts[e]["npm"]), e)):
        lines.append(
            f"| {cell(expression)} | {counts[expression]['python']} | {counts[expression]['npm']} |"
        )
    lines.append("")

    for ecosystem, heading in (
        ("python", "Backend image (Python)"),
        ("npm", "Frontend image (npm)"),
    ):
        rows = [c for c in review.components if c.ecosystem == ecosystem]
        lines += [
            f"## {heading}",
            "",
            f"{len(rows)} distributions.",
            "",
            "| Component | Version | Licence | Source | Evidence |",
            "|---|---|---|---|---|",
        ]
        for component in rows:
            decision = review.policy.reviews.get(component.key)
            evidence = component.evidence
            if decision is not None:
                evidence += f"; review {decision.status}"
            if component.license_file is False:
                notice = review.policy.notices.get(component.key)
                holder = notice.holder if notice is not None else component.attribution
                evidence += f"; no licence file, attributed to {holder}"
            lines.append(
                f"| {cell(component.name)} | {cell(component.version)} | {cell(component.license or '')} "
                f"| {cell(component.source)} | {cell(evidence)} |"
            )
        lines.append("")

    lines += [
        "## Other components",
        "",
        "Recorded by hand in `licenses/components.toml`: the images the containers are",
        "built from and the ones a deployment runs beside them, system packages, fonts",
        "and data files.",
        "",
        "| Component | Version | Kind | Licence | Source | Status | Obligations | How they are met |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in review.manual:
        met = (
            row.fulfilled_by
            if row.status == "accepted"
            else (row.tracked_in or "deployment-time review")
        )
        lines.append(
            f"| {cell(row.name)} | {cell(row.version)} | {cell(row.kind)} | {cell(row.license)} | {cell(row.source)} "
            f"| {row.status} | {cell(row.obligations)} | {cell(met)} |"
        )
    lines.append("")
    return "\n".join(lines)


def comparable(notices: str) -> str:
    """The notices without the evidence cell, which is what `check` compares.

    Two wheels of one release can carry different metadata: `caio` 0.9.25 declares
    `License-Expression: Apache-2.0` on its Linux wheel and nothing on its macOS
    wheel, where the licence is read from the COPYING file instead. The licence is
    the same; only where this machine read it from differs, and that cell records
    exactly that. Comparing it would make the check fail on every laptop that is
    not the runner. A licence, version or source that differs still fails.
    """
    lines: list[str] = []
    for line in notices.splitlines():
        if line.startswith("| ") and line.count(" | ") == 4:
            line = line.rsplit(" | ", 1)[0] + " |"
        lines.append(line)
    return "\n".join(lines)


def print_stale_diff(current: str, rendered: str, limit: int = 80) -> None:
    """The first lines that differ, so a red job says what moved rather than only that it did.

    The notices are regenerated on another machine than the one that committed
    them, so a difference can be a dependency bump or a metadata source that
    reads differently there; the diff is what tells those apart without a
    checkout.
    """
    diff = difflib.unified_diff(
        current.splitlines(), rendered.splitlines(), "committed", "regenerated", lineterm="", n=0
    )
    for index, line in enumerate(diff):
        if index >= limit:
            print("... (diff truncated)")
            break
        print(line)


def verdict(state: str, detail: str) -> None:
    line = f"{VERDICT_PREFIX} {state} - {detail}"
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as handle:
            handle.write(f"{line}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=("write", "check"))
    args = parser.parse_args(argv)

    try:
        review = collect()
    except (MetadataUnavailableError, subprocess.CalledProcessError, ValueError) as error:
        verdict("FAILED", f"inventory did not complete: {error}")
        return EXIT_FAILED

    for problem in review.problems:
        print(problem)
    if review.problems:
        verdict(
            "FAILED",
            f"{len(review.problems)} untracked finding(s); the notices were not {'written' if args.mode == 'write' else 'verified'}",
        )
        return EXIT_FAILED

    rendered = render_notices(review)
    total = len(review.components)
    if args.mode == "write":
        NOTICES_PATH.write_text(rendered)
        verdict(
            "REVIEWED",
            f"{total} components written to {NOTICES_PATH.name}, {len(review.open_findings)} open finding(s)",
        )
        return EXIT_REVIEWED

    current = NOTICES_PATH.read_text() if NOTICES_PATH.exists() else ""
    if comparable(current) != comparable(rendered):
        print_stale_diff(comparable(current), comparable(rendered))
        verdict(
            "FAILED", f"{NOTICES_PATH.name} is stale - run `make licenses` and commit the result"
        )
        return EXIT_FAILED
    verdict("REVIEWED", f"{total} components, {len(review.open_findings)} open finding(s)")
    return EXIT_REVIEWED


if __name__ == "__main__":
    sys.exit(main())
