#!/usr/bin/env python3
"""Verify published images in a disposable local stack; default is a read-only plan.

Run through the backend environment for the real MCP client dependencies:
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0 --run
"""

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
_OBJECT = TypeAdapter(dict[str, JsonValue])
ANSWER = "AgenticOS smoke check passed."


def string(data: dict[str, JsonValue], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Expected a string {key} in the verified response")
    return value


async def exercise(api: str, site: str, password: str) -> dict[str, JsonValue]:
    async with httpx2.AsyncClient(base_url=api, timeout=180, follow_redirects=True) as http:
        ready = await http.get("/api/v1/health/ready")
        ready.raise_for_status()
        console = await http.get(site)
        console.raise_for_status()
        login = await http.post(
            "/api/v1/auth/login", data={"username": "smoke@example.com", "password": password}
        )
        login.raise_for_status()
        token = string(_OBJECT.validate_python(login.json()), "access_token")
        http.headers["Authorization"] = f"Bearer {token}"
        secret = await http.post(
            "/api/v1/secrets",
            json={
                "name": "Local smoke fixture",
                "purpose": "openai",
                "value": {"kind": "api_key", "api_key": "local-fixture-not-a-provider-key"},
            },
        )
        secret.raise_for_status()
        profile = await http.post(
            "/api/v1/providers/model-profiles",
            json={
                "label": "Local smoke fixture",
                "provider": "openai",
                "model": "smoke",
                "api": "chat",
                "base_url": "http://smoke-model:8080/v1",
                "secret_id": string(_OBJECT.validate_python(secret.json()), "id"),
            },
        )
        profile.raise_for_status()
        profile_id = string(_OBJECT.validate_python(profile.json()), "id")
        issued = await http.post(
            "/api/v1/api-keys",
            json={
                "name": "Disposable smoke client",
                "scopes": [
                    "agents:view",
                    "agents:edit",
                    "agents:publish",
                    "agents:run",
                    "runs:view",
                ],
            },
        )
        issued.raise_for_status()
        key = string(_OBJECT.validate_python(issued.json()), "key")
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=180) as http,
        streamable_http_client(api + "/mcp", http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        async def call(name: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
            result = await session.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(f"MCP smoke operation failed: {name}")
            for content in result.content:
                if content.type == "text":
                    return _OBJECT.validate_json(content.text)
            raise RuntimeError(f"MCP operation returned no JSON: {name}")

        identity = await call("whoami", {})
        agent = await call(
            "create_agent_draft",
            {
                "name": "Disposable smoke agent",
                "instructions": "Answer the smoke check.",
                "model_profile_id": profile_id,
            },
        )
        agent_id = string(agent, "id")
        await call("publish_agent", {"agent_id": agent_id})
        run = await call(
            "run_agent", {"agent_id": agent_id, "prompt": "Verify the local installation."}
        )
        if ANSWER not in json.dumps(run) or run.get("status") != "completed":
            raise RuntimeError("Agent run did not complete with the deterministic fixture answer")
        recorded = await call("get_run", {"run_id": string(run, "run_id")})
        if recorded.get("status") != "completed":
            raise RuntimeError("Completed agent run was not persisted")
        return {
            "organization_id": identity["organization_id"],
            "agent_id": agent_id,
            "run_id": run["run_id"],
            "run_status": "completed",
            "console_status": console.status_code,
            "api_ready": True,
            "model": "deterministic local fixture",
            "paid_provider_tested": False,
            "tls_and_external_dns_tested": False,
        }


def run(version: str, report: Path | None, api_port: int, site_port: int) -> None:
    project = "agenticos-smoke-" + secrets.token_hex(4)
    api, site = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{site_port}"
    with tempfile.TemporaryDirectory(prefix=project + "-", delete=False) as folder:
        directory = Path(folder)
        shutil.copyfile(ROOT / "docker-compose.yml", directory / "compose.yml")
        shutil.copyfile(ROOT / "scripts/agenticos_smoke_model.py", directory / "smoke-model.py")
        password = secrets.token_urlsafe(24)
        env = {
            "AGENTICOS_VERSION": version,
            "SECRET_KEY": secrets.token_hex(32),
            "VAULT_MASTER_KEY": secrets.token_hex(32),
            "API_KEY": secrets.token_hex(32),
            "POSTGRES_PASSWORD": secrets.token_hex(24),
            "ENVIRONMENT": "development",
            "UVICORN_WORKERS": "1",
            "DIAGNOSTICS_ENABLED": "false",
            "OUTBOUND_PRIVATE_ALLOWLIST": json.dumps(["smoke-model"]),
            "FRONTEND_URL": site,
            "PUBLIC_SITE_URL": site,
            "PUBLIC_API_URL": api,
            "PUBLIC_BASE_URL": api,
            "PUBLIC_WS_URL": f"ws://127.0.0.1:{api_port}",
            "CORS_ORIGINS": json.dumps([site]),
            "SESSION_COOKIE_NAMESPACE": project,
        }
        env_file = directory / ".env"
        env_file.touch(mode=0o600)
        env_file.write_text("".join(f"{key}={json.dumps(value)}\n" for key, value in env.items()))
        (directory / "overlay.yml").write_text(f"""services:
  app:
    ports: !override ["127.0.0.1:{api_port}:8000"]
  frontend:
    ports: !override ["127.0.0.1:{site_port}:3000"]
  smoke-model:
    image: ghcr.io/vstorm-co/agenticos-backend:{version}
    entrypoint: ["python", "/smoke-model.py"]
    volumes: ["./smoke-model.py:/smoke-model.py:ro"]
    networks: [backend]
""")
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(directory),
            "-p",
            project,
            "-f",
            str(directory / "compose.yml"),
            "-f",
            str(directory / "overlay.yml"),
        ]
        # Compose reads only this disposable configuration, never the caller's
        # project env or project name. Docker connection/auth settings remain usable.
        process_env = {
            key: value
            for key, value in os.environ.items()
            if key not in env
            and not key.startswith(("COMPOSE_", "AGENTICOS_", "POSTGRES_", "PUBLIC_"))
        }
        try:
            print(f"Starting disposable project {project}, release {version}", flush=True)
            subprocess.run(
                [
                    *command,
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "300",
                    "smoke-model",
                    "app",
                    "worker",
                    "frontend",
                ],
                env=process_env,
                check=True,
                timeout=600,
            )
            print("Bootstrapping isolated organization", flush=True)
            subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "app",
                    "agenticos",
                    "cmd",
                    "bootstrap",
                    "--email",
                    "smoke@example.com",
                    "--password",
                    password,
                    "--org",
                    "Smoke test",
                ],
                env=process_env,
                check=True,
                timeout=180,
            )
            result = asyncio.run(exercise(api, site, password))
            result.update({"release": version, "project": project})
            images = subprocess.run(
                [*command, "images", "--format", "json"],
                env=process_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            result["images"] = images.stdout.strip()
            if report is not None:
                report.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2), flush=True)
        except subprocess.CalledProcessError:
            subprocess.run(
                [*command, "logs", "--no-color", "--tail", "60", "migrate", "app"],
                env=process_env,
                check=False,
                timeout=30,
            )
            raise
        finally:
            print(f"Removing disposable project {project} and its volumes", flush=True)
            cleanup = subprocess.run(
                [*command, "down", "--volumes", "--remove-orphans"],
                env=process_env,
                check=False,
                timeout=180,
            )
            if cleanup.returncode:
                print(
                    f"Cleanup failed; disposable configuration retained at {directory}",
                    file=sys.stderr,
                )
                if sys.exception() is None:
                    cleanup.check_returncode()
            else:
                shutil.rmtree(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--run", action="store_true", help="Start and remove a disposable local stack"
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--api-port", type=int, default=18080)
    parser.add_argument("--site-port", type=int, default=13000)
    args = parser.parse_args()
    if not args.version or any(
        char not in "0123456789abcdefghijklmnopqrstuvwxyz.-" for char in args.version
    ):
        parser.error("Choose an explicit release or sha image tag")
    if args.run:
        run(args.version, args.report, args.api_port, args.site_port)
    else:
        print(
            f"Plan: disposable Compose project, release {args.version}, API 127.0.0.1:{args.api_port}, console 127.0.0.1:{args.site_port}; bootstrap, MCP agent run, cleanup. Add --run to execute."
        )


if __name__ == "__main__":
    main()
