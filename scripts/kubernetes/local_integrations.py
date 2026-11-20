"""Configure and exercise optional integrations on an isolated local CRC deployment."""

import argparse
import base64
import json
import secrets
import subprocess
import tempfile
from pathlib import Path

import yaml
from smoke_probe import mapping, rows, text

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "agenticos-smoke"
DEPENDENCIES = "agenticos-smoke-deps"
KEYCLOAK = "https://identity-agenticos-smoke.apps-crc.testing"
POD_SCRIPTS = "/tmp/agenticos-validation"  # noqa: S108 -- The API pod owns this emptyDir path.
BACKEND = "https://api-agenticos-smoke.apps-crc.testing"


class Cluster:
    def __init__(self, kubeconfig: Path) -> None:
        self.kubeconfig = kubeconfig.resolve(strict=True)
        server = self.run("oc", "whoami", "--show-server").strip()
        if server != "https://api.crc.testing:6443":
            raise ValueError(
                "Local integrations refuse a cluster other than CRC api.crc.testing:6443"
            )
        for namespace in (NAMESPACE, DEPENDENCIES):
            resource = self.optional("namespace", namespace, namespace)
            if resource is None:
                raise ValueError(f"Run the local OpenShift base smoke first: missing {namespace}")
            labels = mapping(resource["metadata"]).get("labels", {})
            if mapping(labels).get("agenticos-validation") != "true":
                raise ValueError(f"Refusing namespace not owned by local validation: {namespace}")

    def run(
        self,
        program: str,
        *arguments: str,
        payload: str | None = None,
        timeout: int = 900,
        redact_error: bool = False,
    ) -> str:
        result = subprocess.run(
            [program, "--kubeconfig", str(self.kubeconfig), *arguments],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            # Manifest input can contain generated test credentials; do not echo it.
            detail = (
                "Secret-bearing manifest: details withheld"
                if redact_error
                else result.stderr[-2000:]
            )
            raise RuntimeError(f"{program} {arguments[:3]} failed ({result.returncode}): {detail}")
        return result.stdout

    def apply(self, document: dict[str, object]) -> None:
        print(
            self.run(
                "oc",
                "apply",
                "-f",
                "-",
                payload=json.dumps(document),
                redact_error=document.get("kind") == "Secret",
            ).strip(),
            flush=True,
        )

    def optional(self, kind: str, name: str, namespace: str) -> dict[str, object] | None:
        result = self.run(
            "oc", "-n", namespace, "get", kind, name, "--ignore-not-found", "-o", "json"
        )
        return mapping(json.loads(result)) if result.strip() else None

    def probe(
        self, filename: str, *, certificate: str | None = None, payload: str | None = None
    ) -> None:
        pod = self.api_pod()
        self.run(
            "oc",
            "-n",
            NAMESPACE,
            "exec",
            pod,
            "--",
            "mkdir",
            "-p",
            POD_SCRIPTS,
        )
        if certificate is not None:
            self.run(
                "oc",
                "-n",
                NAMESPACE,
                "exec",
                "-i",
                pod,
                "--",
                "python",
                "-c",
                "import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.stdin.read())",
                f"{POD_SCRIPTS}/router-ca.crt",
                payload=certificate,
            )
        for name in dict.fromkeys(("smoke_probe.py", "oidc_probe.py", filename)):
            self.run(
                "oc",
                "-n",
                NAMESPACE,
                "cp",
                str(ROOT / "scripts/kubernetes" / name),
                f"{pod}:{POD_SCRIPTS}/{name}",
            )
        print(
            self.run(
                "oc",
                "-n",
                NAMESPACE,
                "exec",
                *(["-i"] if payload is not None else []),
                pod,
                "--",
                "python",
                f"{POD_SCRIPTS}/{filename}",
                payload=payload,
            ),
            flush=True,
        )

    def api_pod(self) -> str:
        result = self.run(
            "oc",
            "-n",
            NAMESPACE,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/component=api",
            "-o",
            "json",
        )
        pods = rows(mapping(json.loads(result))["items"])
        ready = [
            mapping(pod)
            for pod in pods
            if mapping(mapping(pod)["status"]).get("phase") == "Running"
            and not mapping(mapping(pod)["metadata"]).get("deletionTimestamp")
            and any(
                mapping(condition).get("type") == "Ready"
                and mapping(condition).get("status") == "True"
                for condition in rows(mapping(mapping(pod)["status"]).get("conditions", []))
            )
        ]
        if len(ready) != 1:
            raise RuntimeError("Expected one running validation API pod")
        return text(mapping(ready[0]["metadata"])["name"])


def router_certificate(cluster: Cluster) -> str:
    encoded = cluster.run(
        "oc",
        "-n",
        "openshift-ingress-operator",
        "get",
        "secret",
        "router-ca",
        "-o",
        "jsonpath={.data.tls\\.crt}",
    )
    return base64.b64decode(encoded).decode()


def sandbox(cluster: Cluster) -> None:
    """Exercise an independently prepared, disposable OpenSandbox fixture."""
    for namespace in ("opensandbox-system", "opensandbox"):
        resource = cluster.optional("namespace", namespace, namespace)
        if (
            resource is None
            or mapping(mapping(resource["metadata"]).get("labels", {})).get("agenticos-validation")
            != "true"
        ):
            raise ValueError("Refusing an OpenSandbox namespace not owned by local validation")
    secret = cluster.optional("secret", "opensandbox-api-key", "opensandbox-system")
    fixture = cluster.optional("deployment", "model-fixture", DEPENDENCIES)
    if secret is None or fixture is None:
        raise ValueError("Prepare the disposable provider and model fixtures first")
    image = text(
        mapping(
            rows(mapping(mapping(mapping(fixture["spec"])["template"])["spec"])["containers"])[0]
        )["image"]
    )
    key = base64.b64decode(text(mapping(secret["data"])["api-key"])).decode()
    cluster.probe(
        "sandbox_probe.py",
        certificate=router_certificate(cluster),
        payload=json.dumps({"api_key": key, "image": image}),
    )
    # The server's deletion acknowledgement must also remove its Kubernetes workload.
    cluster.run(
        "oc", "-n", "opensandbox", "wait", "--for=delete", "batchsandbox", "--all", "--timeout=120s"
    )
    cluster.run(
        "oc", "-n", "opensandbox", "wait", "--for=delete", "pods", "--all", "--timeout=120s"
    )
    print("PASS provider BatchSandbox and pod cleanup", flush=True)


def routes(cluster: Cluster) -> None:
    """Configure CRC-owned edge Routes without disabling TLS verification."""
    ca = router_certificate(cluster)
    roots = cluster.run(
        "oc",
        "-n",
        NAMESPACE,
        "exec",
        "deployment/smoke-agenticos-api",
        "--",
        "python",
        "-c",
        "import certifi; print(certifi.contents())",
    )
    trust = cluster.optional("secret", "agenticos-smoke-ca", NAMESPACE)
    if trust is None:
        raise ValueError("Run the OpenShift base smoke before adding Routes")
    data = mapping(trust["data"])
    data["ssl-roots.pem"] = base64.b64encode((roots + "\n" + ca).encode()).decode()
    cluster.run(
        "oc",
        "apply",
        "--server-side",
        "-f",
        "-",
        payload=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "agenticos-smoke-ca", "namespace": NAMESPACE},
                "data": data,
            }
        ),
        redact_error=True,
    )
    values = mapping(
        json.loads(cluster.run("helm", "get", "values", "smoke", "-n", NAMESPACE, "-o", "json"))
    )
    values["public"] = {
        "siteUrl": "https://app-agenticos-smoke.apps-crc.testing",
        "apiUrl": BACKEND,
        "websocketUrl": "wss://api-agenticos-smoke.apps-crc.testing",
    }
    values["trustedProxy"] = {
        "enabled": True,
        "namespaceLabels": {"kubernetes.io/metadata.name": "openshift-ingress"},
        "podLabels": {
            "ingresscontroller.operator.openshift.io/deployment-ingresscontroller": "default"
        },
    }
    trust_values = mapping(values["trust"])
    trust_values["sslCaKey"] = "ssl-roots.pem"
    values["trust"] = trust_values
    for name, namespace, service, host, port in (
        (
            "validation-api",
            NAMESPACE,
            "smoke-agenticos-api",
            "api-agenticos-smoke.apps-crc.testing",
            "http",
        ),
        (
            "validation-console",
            NAMESPACE,
            "smoke-agenticos-frontend",
            "app-agenticos-smoke.apps-crc.testing",
            "http",
        ),
        (
            "validation-identity",
            DEPENDENCIES,
            "keycloak",
            "identity-agenticos-smoke.apps-crc.testing",
            8080,
        ),
    ):
        cluster.apply(
            {
                "apiVersion": "route.openshift.io/v1",
                "kind": "Route",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "annotations": {"haproxy.router.openshift.io/timeout": "5m"},
                },
                "spec": {
                    "host": host,
                    "to": {"kind": "Service", "name": service},
                    "port": {"targetPort": port},
                    "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"},
                },
            }
        )
    with tempfile.TemporaryDirectory(prefix="agenticos-routes-") as temporary:
        path = Path(temporary) / "values.yaml"
        path.write_text(yaml.safe_dump(values))
        print(
            cluster.run(
                "helm",
                "upgrade",
                "smoke",
                str(ROOT / "charts/agenticos"),
                "-n",
                NAMESPACE,
                "-f",
                str(path),
                "--wait",
                "--timeout",
                "15m",
            ),
            flush=True,
        )
    cluster.probe("route_probe.py", certificate=ca)
    code = """import socket
for host, port in [
    ('smoke-agenticos-api.agenticos-smoke.svc.cluster.local', 8000),
    ('smoke-agenticos-frontend.agenticos-smoke.svc.cluster.local', 3000),
]:
    try:
        with socket.create_connection((host, port), timeout=4):
            pass
    except TimeoutError:
        print('PASS untrusted namespace cannot enter ' + host)
    else:
        raise AssertionError('Untrusted namespace reached a protected service')
"""
    print(
        cluster.run(
            "oc", "-n", DEPENDENCIES, "exec", "deployment/model-fixture", "--", "python", "-c", code
        ),
        flush=True,
    )


def keycloak(cluster: Cluster, *, prepare_only: bool = False) -> None:
    secret = cluster.optional("secret", "local-idp-realm", DEPENDENCIES)
    if secret:
        encoded = text(mapping(secret["data"])["realm.json"])
        realm = mapping(json.loads(base64.b64decode(encoded)))
        clients = rows(realm["clients"])
        client = mapping(clients[0])
        client_secret = text(client["secret"])
        client["redirectUris"] = [f"{BACKEND}/api/v1/oauth/oidc/callback"]
        clients[0] = client
        realm["clients"] = clients
        cluster.apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "local-idp-realm", "namespace": DEPENDENCIES},
                "stringData": {"realm.json": json.dumps(realm)},
            }
        )
    else:
        client_secret = secrets.token_urlsafe(32)
        users = [
            {
                "username": name,
                "enabled": True,
                "email": f"{name}@{'outside.example' if name == 'outside' else 'allowed.example'}",
                "emailVerified": name != "unverified",
                "firstName": "Local",
                "lastName": name,
                "credentials": [
                    {
                        "type": "password",
                        "value": "local-oidc-validation-password",
                        "temporary": False,
                    }
                ],
            }
            for name in ("verified", "unverified", "outside", "uninvited")
        ]
        realm = {
            "realm": "agenticos-local",
            "enabled": True,
            "sslRequired": "none",
            "registrationAllowed": False,
            "clients": [
                {
                    "clientId": "agenticos",
                    "secret": client_secret,
                    "publicClient": False,
                    "standardFlowEnabled": True,
                    "directAccessGrantsEnabled": False,
                    "redirectUris": [f"{BACKEND}/api/v1/oauth/oidc/callback"],
                    "attributes": {"pkce.code.challenge.method": "S256"},
                }
            ],
            "users": users,
        }
        cluster.apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "local-idp-realm", "namespace": DEPENDENCIES},
                "stringData": {"realm.json": json.dumps(realm)},
            }
        )
    cluster.apply(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "keycloak", "namespace": DEPENDENCIES},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"fixture": "keycloak"}},
                "template": {
                    "metadata": {"labels": {"fixture": "keycloak"}},
                    "spec": {
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": "keycloak",
                                "image": "quay.io/keycloak/keycloak:26.8.2",
                                "args": [
                                    "start-dev",
                                    "--import-realm",
                                    f"--hostname={KEYCLOAK}",
                                    "--health-enabled=true",
                                    "--proxy-headers=xforwarded",
                                ],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "ports": [{"containerPort": 8080}],
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "256Mi"},
                                    "limits": {"cpu": "2", "memory": "1Gi"},
                                },
                                "startupProbe": {
                                    "httpGet": {"path": "/health/ready", "port": 9000},
                                    "failureThreshold": 120,
                                    "periodSeconds": 5,
                                },
                                "readinessProbe": {
                                    "httpGet": {"path": "/health/ready", "port": 9000}
                                },
                                "volumeMounts": [
                                    {
                                        "name": "realm",
                                        "mountPath": "/opt/keycloak/data/import",
                                        "readOnly": True,
                                    },
                                    {"name": "data", "mountPath": "/opt/keycloak/data"},
                                ],
                            }
                        ],
                        "volumes": [
                            {"name": "realm", "secret": {"secretName": "local-idp-realm"}},
                            {"name": "data", "emptyDir": {"sizeLimit": "1Gi"}},
                        ],
                    },
                },
            },
        }
    )
    cluster.apply(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "keycloak", "namespace": DEPENDENCIES},
            "spec": {
                "selector": {"fixture": "keycloak"},
                "ports": [{"port": 8080, "targetPort": 8080}],
            },
        }
    )
    print(
        cluster.run(
            "oc", "-n", DEPENDENCIES, "rollout", "status", "deployment/keycloak", "--timeout=600s"
        ),
        flush=True,
    )
    if prepare_only:
        return
    runtime = cluster.optional("secret", "agenticos-smoke", NAMESPACE)
    if runtime is None:
        raise RuntimeError("Run the base deployment smoke first")
    data = mapping(runtime["data"])
    data["OIDC_CLIENT_SECRET"] = base64.b64encode(client_secret.encode()).decode()
    cluster.apply(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "agenticos-smoke", "namespace": NAMESPACE},
            "data": data,
        }
    )
    values = mapping(
        json.loads(cluster.run("helm", "get", "values", "smoke", "-n", NAMESPACE, "-o", "json"))
    )
    extra = mapping(values["extraEnv"])
    extra.update(
        {
            "OIDC_ISSUER": f"{KEYCLOAK}/realms/agenticos-local",
            "OIDC_CLIENT_ID": "agenticos",
            "OIDC_REDIRECT_URI": f"{BACKEND}/api/v1/oauth/oidc/callback",
        }
    )
    values["extraEnv"] = extra
    with tempfile.TemporaryDirectory(prefix="agenticos-oidc-") as temporary:
        path = Path(temporary) / "values.yaml"
        path.write_text(yaml.safe_dump(values))
        print(
            cluster.run(
                "helm",
                "upgrade",
                "smoke",
                str(ROOT / "charts/agenticos"),
                "-n",
                NAMESPACE,
                "-f",
                str(path),
                "-f",
                str(ROOT / "charts/agenticos/values-openshift.yaml"),
                "--wait",
                "--timeout",
                "15m",
            ),
            flush=True,
        )
    encoded_ca = cluster.run(
        "oc",
        "-n",
        "openshift-ingress-operator",
        "get",
        "secret",
        "router-ca",
        "-o",
        "jsonpath={.data.tls\\.crt}",
    )
    cluster.probe("oidc_probe.py", certificate=base64.b64decode(encoded_ca).decode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("integration", choices=("routes", "oidc", "prepare-oidc", "sandbox"))
    args = parser.parse_args()
    if not isinstance(args.kubeconfig, Path):
        raise TypeError("Expected an explicit local kubeconfig path")
    cluster = Cluster(args.kubeconfig)
    if args.integration == "routes":
        routes(cluster)
    elif args.integration == "sandbox":
        sandbox(cluster)
    else:
        keycloak(cluster, prepare_only=args.integration == "prepare-oidc")


if __name__ == "__main__":
    main()
