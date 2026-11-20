"""Exercise the shipped proxies and Compose files with Docker, without app data.

Run from the repository root: make test-deployment
Only disposable, uniquely named containers/networks and temporary files are used.
No ACME request can leave the test: its directory URL is loopback port 9.
"""

import http.client
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 * 1024
# A transport fixture: only Upgrade requests receive 101, and uploads report the
# number of bytes that actually reached the upstream, including chunked bodies.
UPSTREAM = r"""
import base64
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers["Sec-WebSocket-Key"]
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.close_connection = True
            return
        self.reply({"host": self.headers.get("Host"),
                    "proto": self.headers.get("X-Forwarded-Proto"),
                    "upgrade": self.headers.get("Upgrade")})

    def do_POST(self):
        size = 0
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                length = int(self.rfile.readline().strip(), 16)
                if not length:
                    self.rfile.readline()
                    break
                size += len(self.rfile.read(length))
                self.rfile.read(2)
        else:
            remaining = int(self.headers.get("Content-Length", "0"))
            while remaining:
                chunk = self.rfile.read(min(remaining, 65536))
                size += len(chunk)
                remaining -= len(chunk)
        self.reply({"bytes": size})

    def reply(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
"""


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise AssertionError(f"{' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict), value
    assert all(isinstance(key, str) for key in value)
    return {str(key): item for key, item in value.items()}


class DeploymentProxies(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="agenticos-proxies-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.network = f"agenticos-proxies-{uuid4().hex[:12]}"
        run("docker", "network", "create", cls.network)
        cls.addClassCleanup(run, "docker", "network", "rm", cls.network)
        for source in ROOT.glob("docker-compose*.yml"):
            shutil.copy(source, cls.directory / source.name)
        (cls.directory / "backend").mkdir()
        cls.env = cls.directory / "backend/.env"
        cls.env.write_text(
            "POSTGRES_PASSWORD=test-only\nREDIS_PASSWORD=test-only\n"
            "PUBLIC_API_URL=https://api.example.test\nPUBLIC_WS_URL=wss://api.example.test\n"
            "PUBLIC_SITE_URL=https://app.example.test\nAPI_DOMAIN=api.example.test\n"
            "SITE_DOMAIN=app.example.test\nACME_EMAIL=ops@example.test\n"
            f"TRAEFIK_NETWORK={cls.network}\nUPDATE_STATE_DIR=/tmp/agenticos-updater\n"
        )
        (cls.directory / "upstream.py").write_text(UPSTREAM)
        run(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(cls.directory / "key.pem"),
            "-out",
            str(cls.directory / "cert.pem"),
            "-subj",
            "/CN=example.test",
        )
        for service, overlay in (
            ("app", "docker-compose-prod.traefik.yml"),
            ("frontend", "docker-compose-prod.frontend.traefik.yml"),
        ):
            base = (
                "docker-compose-prod.yml"
                if service == "app"
                else "docker-compose-prod.frontend.yml"
            )
            spec = mapping(mapping(cls.compose(base, overlay)["services"])[service])
            labels = mapping(spec["labels"])
            args = [
                "--network-alias",
                "backend" if service == "app" else "frontend",
                "--label",
                f"agenticos-proxy-test={cls.network}",
            ]
            for key, value in labels.items():
                args += ["--label", f"{key}={value}"]
            cls.container(
                service,
                "python:3.15-alpine",
                *args,
                "-v",
                f"{cls.directory / 'upstream.py'}:/upstream.py:ro",
                command=("python", "/upstream.py", "8000" if service == "app" else "3000"),
            )
        config = (ROOT / "nginx/nginx.conf").read_text()
        config = config.replace("api.${DOMAIN:-localhost}", "api.example.test")
        config = config.replace("${DOMAIN:-localhost}", "app.example.test")
        config = config.replace("127.0.0.1:8000", "backend:8000").replace(
            "127.0.0.1:3000", "frontend:3000"
        )
        (cls.directory / "nginx.conf").write_text(config)
        cls.nginx = cls.container(
            "nginx",
            os.environ.get("NGINX_IMAGE", "nginx:stable-alpine"),
            "-p",
            "127.0.0.1::443",
            "-v",
            f"{cls.directory / 'nginx.conf'}:/etc/nginx/conf.d/default.conf:ro",
            "-v",
            f"{cls.directory}:/etc/nginx/ssl:ro",
        )
        run("docker", "exec", cls.nginx, "nginx", "-t")
        traefik = mapping(mapping(cls.compose("docker-compose-traefik.yml")["services"])["traefik"])
        command = traefik["command"]
        assert isinstance(command, list) and all(isinstance(arg, str) for arg in command)
        command = [str(arg) for arg in command if arg != "--log.level=INFO"]
        # Debug exposes the config Traefik actually loaded, including ACME email.
        command += [
            "--log.level=DEBUG",
            "--log.nocolor=true",
            f"--providers.docker.constraints=Label(`agenticos-proxy-test`, `{cls.network}`)",
            "--certificatesresolvers.letsencrypt.acme.caserver=http://127.0.0.1:9/directory",
        ]
        args = []
        # Keep the source's mounts: accidentally reintroducing a static file
        # must reproduce Traefik ignoring the command arguments.
        volumes = traefik["volumes"]
        assert isinstance(volumes, list)
        for mount in volumes:
            item = mapping(mount)
            if item["type"] == "bind":
                source = str(item["source"]).replace(str(cls.directory), str(ROOT), 1)
                args += ["-v", f"{source}:{item['target']}:ro"]
        cls.traefik = cls.container(
            "traefik", str(traefik["image"]), *args, "-p", "127.0.0.1::443", command=tuple(command)
        )
        cls.ports = {
            name: int(run("docker", "port", container, "443/tcp").rsplit(":", 1)[1])
            for name, container in (("nginx", cls.nginx), ("traefik", cls.traefik))
        }
        for name in cls.ports:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    status, _, _ = cls.request(name, "api.example.test", "GET", "/ready")
                    if status == 200:
                        break
                except OSError, http.client.HTTPException:
                    # A proxy may still be binding its listener during startup.
                    pass
                time.sleep(0.25)
            else:
                raise AssertionError(
                    run("docker", "logs", cls.nginx if name == "nginx" else cls.traefik)
                )

    @classmethod
    def compose(cls, *files: str) -> dict[str, object]:
        args = ["docker", "compose", "--env-file", str(cls.env), "--profile", "*"]
        for file in files:
            args += ["-f", str(cls.directory / file)]
        # Prevent a caller's shell from overriding the synthetic fixture values.
        result = subprocess.run(
            [*args, "config", "--format", "json"],
            env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return mapping(json.loads(result.stdout))

    @classmethod
    def container(cls, name: str, image: str, *args: str, command: tuple[str, ...] = ()) -> str:
        name = f"{cls.network}-{name}"
        run("docker", "run", "-d", "--name", name, "--network", cls.network, *args, image, *command)
        cls.addClassCleanup(run, "docker", "rm", "-f", name)
        return name

    @classmethod
    def request(
        cls,
        proxy: str,
        host: str,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        # These disposable proxies deliberately use self-signed test certificates.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(
            "127.0.0.1", cls.ports[proxy], context=context, timeout=20
        )
        try:
            connection.request(method, path, body, {"Host": host, **(headers or {})})
            response = connection.getresponse()
            return (
                response.status,
                response.read(),
                {key.lower(): value for key, value in response.getheaders()},
            )
        finally:
            connection.close()

    def test_websockets_on_every_api_surface(self) -> None:
        paths = [
            "/api/v1/ws/agent",
            "/api/v1/ws/events",
            "/api/v1/ws/voice",
            "/api/v1/ws/device",
            "/api/v1/ws/workflow-runs",
            "/api/v1/ws/browse/RUN/CALL",
            "/api/v1/embed/KEY/ws",
            "/api/v1/embed/KEY/voice/ws",
            "/api/v1/phone/media/CALL",
        ]
        for proxy in self.ports:
            for path in paths:
                with self.subTest(proxy=proxy, path=path):
                    status, _, headers = self.request(
                        proxy,
                        "api.example.test",
                        "GET",
                        path,
                        headers={
                            "Upgrade": "websocket",
                            "Connection": "Upgrade",
                            "Sec-WebSocket-Version": "13",
                            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                        },
                    )
                    self.assertEqual(status, 101)
                    self.assertEqual(
                        headers["sec-websocket-accept"], "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
                    )

    def test_uploads_reach_both_upstreams(self) -> None:
        for proxy in self.ports:
            for host in ("api.example.test", "app.example.test"):
                for size in (2 * MIB, 50 * MIB):
                    with self.subTest(proxy=proxy, host=host, size=size):
                        body = b'--file\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\n'
                        body += b"x" * size + b"\r\n--file--\r\n"
                        status, data, _ = self.request(
                            proxy,
                            host,
                            "POST",
                            "/api/kb/KB/documents",
                            body,
                            {"Content-Type": "multipart/form-data; boundary=file"},
                        )
                        self.assertEqual(status, 200)
                        self.assertEqual(mapping(json.loads(data))["bytes"], len(body))

    def test_nginx_refuses_bodies_over_the_envelope_ceiling(self) -> None:
        for host in ("api.example.test", "app.example.test"):
            status, _, _ = self.request(
                "nginx",
                host,
                "POST",
                "/api/kb/KB/documents",
                headers={"Content-Length": str(55 * MIB + 1)},
            )
            self.assertEqual(status, 413)

    def test_nginx_keeps_a_small_limit_on_authentication_and_json(self) -> None:
        for path in (
            "/api/auth/login",
            "/api/auth/register",
            "/api/invitations/stage",
            "/api/users/me",
            "/ordinary",
        ):
            with self.subTest(path=path):
                status, _, _ = self.request(
                    "nginx",
                    "app.example.test",
                    "POST",
                    path,
                    headers={"Content-Type": "application/json", "Content-Length": str(2 * MIB)},
                )
                self.assertEqual(status, 413)

    def test_nginx_allows_every_console_upload_route(self) -> None:
        paths = (
            "files/upload",
            "kb/KB/documents",
            "rag/collections/KB/ingest",
            "projects/ID/files",
            "skills/ID/resources/upload",
            "datasets/ID/import",
            "users/me/avatar",
            "orgs/ID/avatar",
            "admin/organizations/ID/avatar",
            "admin/settings/logo",
            "admin/settings/favicon",
            "agents/ID/avatar",
            "agents/ID/dictation",
            "agents/ID/embeds/ID/logo",
            "ml/documents/analyze",
            "ml/documents/ocr",
            "ml/audio/transcriptions",
            "tables/ID/media",
            "conversations/ID/visuals/ID/thumbnail",
        )
        for path in paths:
            for suffix in ("", "/"):
                with self.subTest(path=path, suffix=suffix):
                    body = b"x" * (2 * MIB)
                    status, data, _ = self.request(
                        "nginx",
                        "app.example.test",
                        "POST",
                        f"/api/{path}{suffix}",
                        body,
                        {"Content-Type": "multipart/form-data; boundary=test"},
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(mapping(json.loads(data))["bytes"], len(body))

    def test_normal_http_keeps_forwarded_origin_and_hsts(self) -> None:
        for proxy in self.ports:
            for host in ("api.example.test", "app.example.test"):
                with self.subTest(proxy=proxy, host=host):
                    status, data, headers = self.request(proxy, host, "GET", "/ordinary")
                    self.assertEqual(status, 200)
                    self.assertEqual(
                        mapping(json.loads(data)), {"host": host, "proto": "https", "upgrade": None}
                    )
                    self.assertIn("max-age=31536000", headers["strict-transport-security"])

    def test_traefik_loads_acme_email_and_private_discovery(self) -> None:
        logs = run("docker", "logs", self.traefik)
        line = next(line for line in logs.splitlines() if "staticConfiguration=" in line)
        config = mapping(json.loads(line.split("staticConfiguration=", 1)[1]))
        acme = mapping(mapping(mapping(config["certificatesResolvers"])["letsencrypt"])["acme"])
        self.assertEqual(acme["email"], "ops@example.test")
        self.assertEqual(mapping(mapping(config["providers"])["docker"])["network"], self.network)
        self.assertFalse(
            mapping(mapping(config["providers"])["docker"]).get("exposedByDefault", False)
        )
        self.assertEqual(
            mapping(mapping(mapping(config["accessLog"])["fields"])["names"])["RequestPath"], "drop"
        )

    def test_image_build_contexts_exclude_environment_files(self) -> None:
        for context_name, ignore_file, prefix in (
            ("frontend", "frontend/.dockerignore", ""),
            ("backend", ".dockerignore", "backend/"),
        ):
            with self.subTest(context=context_name):
                context = self.directory / f"build-{context_name}"
                context.mkdir()
                (context / ".dockerignore").write_text((ROOT / ignore_file).read_text())
                (context / "Dockerfile").write_text("FROM scratch\nCOPY . /\n")
                target = context / prefix
                target.mkdir(exist_ok=True)
                names = (
                    ".env",
                    ".env.local",
                    ".env.production",
                    ".env.development",
                    ".env.test",
                    ".env.production.local",
                )
                for name in (*names, ".env.example"):
                    (target / name).write_text("SYNTHETIC_BUILD_SENTINEL=not-a-credential\n")
                output = self.directory / f"export-{context_name}"
                run("docker", "build", "--output", f"type=local,dest={output}", str(context))
                for name in names:
                    self.assertFalse(
                        (output / prefix / name).exists(),
                        f"{context_name}: {name} entered the image",
                    )
                self.assertTrue((output / prefix / ".env.example").exists())

    def test_production_networks_and_migration_gate(self) -> None:
        backend = self.compose("docker-compose-prod.yml")
        frontend = self.compose("docker-compose-prod.frontend.yml")
        services = mapping(backend["services"])
        app = mapping(services["app"])
        worker = mapping(services["worker"])
        self.assertEqual(app["image"], worker["image"])
        for service in (app, worker):
            self.assertEqual(
                mapping(mapping(service["depends_on"])["migrate"])["condition"],
                "service_completed_successfully",
            )
            volumes = service["volumes"]
            assert isinstance(volumes, list)
            self.assertFalse(
                any(mapping(volume)["target"] == "/var/run/docker.sock" for volume in volumes)
            )
        for name in ("db", "redis"):
            self.assertFalse(mapping(services[name]).get("ports"))
            self.assertEqual(set(mapping(mapping(services[name])["networks"])), {"data"})
        self.assertTrue(mapping(mapping(backend["networks"])["data"])["internal"])
        self.assertEqual(
            mapping(mapping(backend["networks"])["edge"])["name"],
            mapping(mapping(frontend["networks"])["edge"])["name"],
        )
        console = mapping(mapping(frontend["services"])["frontend"])
        for service in (app, console):
            ports = service["ports"]
            assert isinstance(ports, list)
            self.assertTrue(ports)
            self.assertTrue(all(mapping(port)["host_ip"] == "127.0.0.1" for port in ports))

    def test_compose_variants_render(self) -> None:
        variants = [
            ("docker-compose.yml",),
            ("docker-compose.yml", "docker-compose.override.yml"),
            ("docker-compose-dev.yml",),
            ("docker-compose-dev.frontend.yml",),
            ("docker-compose-prod.yml",),
            ("docker-compose-prod.frontend.yml",),
            ("docker-compose-prod.yml", "docker-compose-prod.traefik.yml"),
            ("docker-compose-prod.frontend.yml", "docker-compose-prod.frontend.traefik.yml"),
            ("docker-compose-prod.yml", "docker-compose-prod.updater.yml"),
            ("docker-compose-traefik.yml",),
            ("docker-compose.test.yml",),
        ]
        for files in variants:
            with self.subTest(files=files):
                self.assertTrue(self.compose(*files)["services"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
