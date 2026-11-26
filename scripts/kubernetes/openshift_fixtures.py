"""Disposable data services using OpenShift-assigned identities, not production storage."""

import json
from pathlib import Path

from smoke_probe import mapping, rows

POD_TMP = "/tmp"  # noqa: S108 -- Names a pod-private emptyDir, not a host temporary file.


def fixtures() -> dict[str, object]:
    source: object = json.loads((Path(__file__).parent / "fixtures.json").read_text())
    document = mapping(source)
    resources: list[object] = []
    for item in rows(document["items"]):
        resource = mapping(item)
        if resource["kind"] == "Deployment":
            resource_spec = mapping(resource["spec"])
            template = mapping(resource_spec["template"])
            spec = mapping(template["spec"])
            spec["securityContext"] = {
                "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"},
            }
            container = mapping(rows(spec["containers"])[0])
            container["securityContext"] = {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            }
            volumes = rows(spec.get("volumes", []))
            mounts = rows(container.get("volumeMounts", []))
            env = rows(container["env"])
            volumes.append({"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}})
            mounts.append({"name": "tmp", "mountPath": POD_TMP})
            container["workingDir"] = POD_TMP
            if container["name"] == "postgres":
                env.append({"name": "PGDATA", "value": f"{POD_TMP}/pgdata"})
                volumes.append({"name": "sockets", "emptyDir": {"sizeLimit": "16Mi"}})
                mounts.append({"name": "sockets", "mountPath": "/var/run/postgresql"})
            if container["name"] == "minio":
                env.append({"name": "HOME", "value": POD_TMP})
                volumes.append({"name": "objects", "emptyDir": {"sizeLimit": "2Gi"}})
                mounts.append({"name": "objects", "mountPath": "/data"})
            container["env"] = env
            container["volumeMounts"] = mounts
            spec["volumes"] = volumes
            spec["containers"] = [container]
            template["spec"] = spec
            resource_spec["template"] = template
            resource["spec"] = resource_spec
        resources.append(resource)
    document["items"] = resources
    return document


if __name__ == "__main__":
    print(json.dumps(fixtures()))
