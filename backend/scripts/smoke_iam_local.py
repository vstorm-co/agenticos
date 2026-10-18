#!/usr/bin/env python3
"""Smoke test: minerp IAM login → AgenticOS accepts JWT + JIT user.

Usage (from apps/agentra/backend):
  uv run python scripts/smoke_iam_local.py
  SMOKE_EMAIL=admin@example.com SMOKE_PASSWORD=Demo@123 uv run python scripts/smoke_iam_local.py

Requires: services/auth :8000, AgenticOS :8800 with IAM_AUTH_ENABLED=true.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_EMAIL = "admin@klabsystem.vn"
DEFAULT_PASSWORD = "Demo@123"

AUTH_BASE = os.environ.get("SMOKE_AUTH_URL", "http://127.0.0.1:8000").rstrip("/")
AGENTRA_BASE = os.environ.get("SMOKE_AGENTRA_URL", "http://127.0.0.1:8800").rstrip("/")
BFF_BASE = os.environ.get("SMOKE_BFF_URL", "http://127.0.0.1:5003").rstrip("/")
EMAIL = os.environ.get("SMOKE_EMAIL", DEFAULT_EMAIL)
PASSWORD = os.environ.get("SMOKE_PASSWORD", DEFAULT_PASSWORD)


def _request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            if not body:
                return resp.status, None
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def _ok(label: str) -> None:
    print(f"  OK  {label}")


def _fail(label: str, detail: str) -> None:
    print(f"  FAIL {label}: {detail}")


def main() -> int:
    print("Agentra IAM local smoke")
    print(f"  auth={AUTH_BASE} agentra={AGENTRA_BASE} bff={BFF_BASE}")
    failures = 0

    code, body = _request("GET", f"{AGENTRA_BASE}/api/v1/health/ready")
    if code == 200 and isinstance(body, dict) and body.get("status") == "ready":
        _ok("AgenticOS ready")
    else:
        failures += 1
        _fail("AgenticOS ready", f"HTTP {code} {body!r}")

    code, _ = _request("GET", f"{AUTH_BASE}/api/v1/health/ready")
    if code in (200, 503):
        _ok(f"Auth reachable (HTTP {code}; 503 OK if only Redis down)")
    else:
        failures += 1
        _fail("Auth reachable", f"HTTP {code}")

    form = urllib.parse.urlencode({"username": EMAIL, "password": PASSWORD}).encode()
    code, tokens = _request(
        "POST",
        f"{AUTH_BASE}/api/v1/auth/login",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if code != 200 or not isinstance(tokens, dict) or not tokens.get("access_token"):
        failures += 1
        _fail("IAM login", f"HTTP {code} {tokens!r}")
        print("\nHint: set SMOKE_EMAIL / SMOKE_PASSWORD or run demo seed users.")
        return 1
    access = tokens["access_token"]
    _ok(f"IAM login as {EMAIL}")

    code, me_iam = _request(
        "GET",
        f"{AUTH_BASE}/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    if code != 200 or not isinstance(me_iam, dict) or not me_iam.get("id"):
        failures += 1
        _fail("IAM /auth/me", f"HTTP {code} {me_iam!r}")
    else:
        perms = me_iam.get("permissions") if "permissions" in me_iam else "(in JWT only)"
        _ok(f"IAM profile id={me_iam.get('id')} admin_tier={me_iam.get('admin_tier', '?')}")

    code, me_agentra = _request(
        "GET",
        f"{AGENTRA_BASE}/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    if code != 200 or not isinstance(me_agentra, dict):
        failures += 1
        _fail("AgenticOS /auth/me (IAM JWT)", f"HTTP {code} {me_agentra!r}")
        if code == 401:
            print("  Hint: IAM_AUTH_ENABLED + IAM_JWT_SECRET_KEY must match auth SECRET_KEY")
            print("  Hint: :8800 must run BMS apps/agentra/backend (not legacy pttcos image)")
        if code == 401 and isinstance(me_agentra, dict):
            detail = me_agentra.get("detail") or me_agentra
            if "permission" in str(detail).lower():
                print("  Hint: assign role with agentra.console:read on IAM user")
    else:
        _ok(f"AgenticOS user id={me_agentra.get('id')} email={me_agentra.get('email')}")

    code, bff_body = _request("GET", f"{BFF_BASE}/")
    if code == 200:
        _ok("Console UI (:5003)")
    elif code == 0:
        print(f"  SKIP console UI — {bff_body}")
    else:
        print(f"  SKIP console UI (HTTP {code})")

    code, _ = _request("GET", f"{BFF_BASE}/api/auth/me")
    if code == 401:
        _ok("BFF /api/auth/me without cookie -> 401 (expected)")
    elif code == 200:
        print("  WARN BFF /api/auth/me returned 200 without cookie (unexpected)")
    elif code == 0:
        print(f"  SKIP BFF /api/auth/me — {bff_body}")
    else:
        print(f"  SKIP BFF /api/auth/me (HTTP {code})")

    code, perms_body = _request(
        "GET",
        f"{AGENTRA_BASE}/api/v1/me/permissions",
        headers={"Authorization": f"Bearer {access}"},
    )
    if code == 200 and isinstance(perms_body, dict):
        entries = perms_body.get("permissions") or []
        has_agents_view = any(
            isinstance(e, dict) and e.get("permission") == "agents:view" for e in entries
        )
        if has_agents_view:
            _ok("/me/permissions includes agents:view")
        else:
            failures += 1
            _fail("/me/permissions", f"missing agents:view in {len(entries)} entries")
    else:
        failures += 1
        _fail("/me/permissions", f"HTTP {code} {perms_body!r}")

    login_payload = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    code, login_body = _request(
        "POST",
        f"{BFF_BASE}/api/auth/login",
        data=login_payload,
        headers={"Content-Type": "application/json"},
    )
    if code == 0:
        print(f"  SKIP BFF login — {login_body}")
    elif code == 200 and isinstance(login_body, dict) and login_body.get("user", {}).get("email"):
        _ok(f"BFF login user={login_body['user']['email']}")
    elif code != 200:
        failures += 1
        _fail("BFF login", f"HTTP {code} {login_body!r}")

    print()
    if failures:
        print(f"FAILED ({failures} check(s))")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
