"""A stateful Docker CLI boundary for deployment-script tests; no real daemon."""

import hashlib
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field


class Image(BaseModel):
    id: str
    created: str
    tags: list[str]
    digests: list[str] = Field(default_factory=list)
    parent: str = ""


class Container(BaseModel):
    id: str
    image: str
    reference: str = ""
    service: str = "app"
    working_dir: str = "/stack"
    health: str = "healthy"
    running: bool = True


class Engine(BaseModel):
    images: list[Image] = Field(default_factory=list)
    containers: list[Container] = Field(default_factory=list)
    calls: list[list[str]] = Field(default_factory=list)
    root: str = "/docker-store"
    operating_system: str = "Ubuntu"
    host_available_kib: int = 10 * 1024 * 1024
    available_kib: int = 10 * 1024 * 1024
    reclaim_kib: int = 1024 * 1024
    fail: str = ""
    fail_up: bool = False
    pull_cost_kib: int = 0
    late_container_image: str = ""
    target: str = "a" * 40

    def image(self, reference: str) -> Image:
        return next(i for i in self.images if i.id == reference or reference in i.tags)

    def disk_report(self, available: int) -> str:
        return f"Filesystem 1024-blocks Used Available Capacity Mounted on\nstore 99999999 0 {available} 1% /\n"

    def execute(self, command: str, args: list[str], stdin: bytes = b"") -> str:
        self.calls.append([command, *args])
        if self.fail and " ".join([command, *args]).startswith(self.fail):
            raise RuntimeError("injected CLI failure")
        if command == "git":
            if args[0] == "hash-object":
                return hashlib.sha1(
                    f"blob {len(stdin)}\0".encode() + stdin, usedforsecurity=False
                ).hexdigest()
            return self.target if args[0] == "rev-parse" else ""
        if command == "df":
            return self.disk_report(
                self.host_available_kib
                if "Docker Desktop" in self.operating_system
                else self.available_kib
            )
        if args[:2] == ["manifest", "inspect"]:
            return "{}"
        if args[0] == "info":
            return self.operating_system if "OperatingSystem" in args[-1] else self.root
        if (
            args[0] == "run"
            and "--entrypoint" in args
            and args[args.index("--entrypoint") + 1] == "df"
        ):
            self.image(args[-3])
            return self.disk_report(self.available_kib)
        if args[:2] == ["image", "ls"]:
            if "--quiet" in args:
                images = self.images
                if not args[-1].startswith("--"):
                    images = [
                        i for i in images if any(t.rsplit(":", 1)[0] == args[-1] for t in i.tags)
                    ]
                return "\n".join(i.id for i in images)
            return "\n".join(
                t for i in self.images for t in i.tags if t.rsplit(":", 1)[0] == args[-1]
            )
        if args[:2] == ["image", "inspect"]:
            image = self.image(args[-1])
            template = args[3]
            if ".RepoTags" in template:
                return "\n".join(image.tags)
            if ".RepoDigests" in template:
                return "\n".join(image.digests)
            if ".Created" in template:
                return image.created
            return image.id
        if args[:2] == ["image", "tag"]:
            image = self.image(args[2])
            for existing in self.images:
                existing.tags = [t for t in existing.tags if t != args[3]]
            image.tags.append(args[3])
            return ""
        if args[:2] == ["image", "rm"]:
            refs = [ref for ref in args[2:] if ref != "--no-prune"]
            images = {self.image(ref).id for ref in refs}
            if any(c.image in images for c in self.containers):
                raise RuntimeError("image is referenced by a container")
            for image in list(self.images):
                image.tags = [t for t in image.tags if t not in refs]
                if image.id in images and not image.tags:
                    self.images.remove(image)
                    self.available_kib += self.reclaim_kib
                    if image.parent and "--no-prune" not in args:
                        parent = self.image(image.parent)
                        if not parent.tags and not any(
                            c.image == parent.id for c in self.containers
                        ):
                            self.images.remove(parent)
            return "removed"
        if args[:2] == ["image", "prune"]:
            return "dangling images only"
        if args[0] == "ps":
            if (
                args[1] == "-aq"
                and self.late_container_image
                and sum(c[:2] == ["docker", "ps"] for c in self.calls) > 1
            ):
                self.containers.append(
                    Container(id="late", image=self.late_container_image, running=False)
                )
                self.late_container_image = ""
            selected = [c for c in self.containers if args[1] == "-aq" or c.running]
            for option in args:
                if option.startswith("label=com.docker.compose.project.working_dir="):
                    selected = [c for c in selected if c.working_dir == option.split("=", 2)[2]]
                if option.startswith("label=com.docker.compose.service="):
                    selected = [c for c in selected if c.service == option.split("=", 2)[2]]
            return "\n".join(c.id for c in selected)
        if args[0] == "inspect":
            if args[2] == "{{.Image}}":
                return "\n".join(
                    next(c.image for c in self.containers if c.id == cid) for cid in args[3:]
                )
            container = next(c for c in self.containers if c.id == args[-1])
            if ".Config.Image" in args[2]:
                return f"{container.image}|{container.reference}|{container.service}|{container.health}"
            return container.health if ".Health.Status" in args[2] else container.image
        if args[0] == "compose":
            if "pull" in args:
                self.available_kib -= self.pull_cost_kib
            if "ps" in args:
                return next(c.id for c in self.containers if c.service == args[-1])
            if "up" in args:
                if self.fail_up:
                    raise RuntimeError("injected start failure")
                service = "frontend" if "-p" in args else "app"
                repo = "frontend" if service == "frontend" else "backend"
                image = self.image(f"ghcr.io/vstorm-co/agenticos-{repo}:sha-{self.target[:7]}")
                self.containers = [c for c in self.containers if c.service != service]
                self.containers.append(Container(id=service, image=image.id, service=service))
            return ""
        raise RuntimeError(f"unexpected Docker command: {args}")


def fake_command() -> None:
    path = Path(os.environ["RETENTION_TEST_STATE"])
    state = Engine.model_validate_json(path.read_text())
    try:
        command = Path(sys.argv[0]).name
        stdin = (
            sys.stdin.buffer.read() if command == "git" and sys.argv[1] == "hash-object" else b""
        )
        output = state.execute(command, sys.argv[1:], stdin)
    except (RuntimeError, StopIteration) as error:
        sys.stderr.write(f"{error}\n")
        status = 1
    else:
        sys.stdout.write(f"{output}\n")
        status = 0
    path.write_text(state.model_dump_json())
    sys.exit(status)
