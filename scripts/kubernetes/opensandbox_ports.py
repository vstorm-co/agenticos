#!/usr/bin/env python3
"""Helm post-renderer: let the pinned OpenSandbox server bind an unprivileged port.

The 1.2.1 server chart hardcodes containerPort 80. Pair this renderer with
configToml's server.port=8080; the Service and probes use the named HTTP port.
"""

import sys

import yaml
from smoke_probe import mapping, rows


def render(source: str) -> str:
    documents: list[dict[str, object]] = []
    changed = 0
    for raw in yaml.safe_load_all(source):
        if raw is None:
            continue
        document = mapping(raw)
        metadata = mapping(document["metadata"])
        if document["kind"] == "Deployment" and metadata["name"] == "opensandbox-server":
            spec = mapping(document["spec"])
            template = mapping(spec["template"])
            pod = mapping(template["spec"])
            containers: list[object] = []
            for item in rows(pod["containers"]):
                container = mapping(item)
                ports: list[object] = []
                for value in rows(container.get("ports", [])):
                    port = mapping(value)
                    if port.get("name") == "http":
                        if port["containerPort"] != 80:
                            raise ValueError(
                                "Reassess this renderer: the upstream HTTP port changed"
                            )
                        port["containerPort"] = 8080
                        changed += 1
                    ports.append(port)
                container["ports"] = ports
                containers.append(container)
            pod["containers"] = containers
            template["spec"] = pod
            spec["template"] = template
            document["spec"] = spec
        documents.append(document)
    if changed != 1:
        raise ValueError("Expected exactly one OpenSandbox server HTTP port")
    return yaml.safe_dump_all(documents, sort_keys=False)


if __name__ == "__main__":
    sys.stdout.write(render(sys.stdin.read()))
