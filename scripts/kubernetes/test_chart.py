"""Render the real chart and enforce deployment and refusal contracts."""

import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from local_integrations import Cluster, keycloak
from model_fixture import sandbox_message
from opensandbox_ports import render as render_ports
from openshift_fixtures import fixtures

ROOT = Path(__file__).resolve().parents[2]
HELM = os.environ.get("HELM", "helm")


def obj(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a Kubernetes object")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Expected a Kubernetes array")
    return list(value)


def at(value: object, *path: str) -> object:
    for key in path:
        value = obj(value)[key]
    return value


def render(*arguments: str) -> list[dict[str, object]]:
    result = subprocess.run(
        [
            HELM,
            "template",
            "smoke",
            str(ROOT / "charts/agenticos"),
            "-f",
            str(ROOT / "scripts/kubernetes/smoke-values.yaml"),
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [obj(value) for value in yaml.safe_load_all(result.stdout)]


class ChartTest(unittest.TestCase):
    def test_oidc_upgrade_preserves_the_installed_candidate_images(self) -> None:
        for digest in ("", "sha256:" + "a" * 64):
            with self.subTest(digest=digest):
                self._assert_oidc_preserves_images(digest)

    def _assert_oidc_preserves_images(self, digest: str) -> None:
        values = {
            "image": {
                "backend": "example/backend",
                "frontend": "example/console",
                "tag": "candidate-1.82.2",
                "frontendTag": "candidate-console",
                "backendDigest": digest,
                "frontendDigest": digest,
            },
            "frontend": {"extraEnv": {"OIDC_PROVIDER_NAME": "Local SSO"}},
            "extraEnv": {"PUBLIC_API_URL": "https://api.candidate.test"},
        }
        cluster = Mock(spec=Cluster)
        cluster.optional.side_effect = [
            None,
            {"data": {"existing": "preserved"}},
        ]
        upgrades: list[tuple[str, ...]] = []
        submitted: list[dict[str, object]] = []

        def run(*args: str) -> str:
            if args[:3] == ("helm", "get", "values"):
                return json.dumps(values)
            if args[:2] == ("helm", "upgrade"):
                upgrades.append(args)
                submitted.append(obj(yaml.safe_load(Path(args[args.index("-f") + 1]).read_text())))
                return "Upgraded"
            if "router-ca" in args:
                return base64.b64encode(b"local-test-certificate").decode()
            return "Ready"

        cluster.run.side_effect = run
        keycloak(cluster)
        self.assertEqual(len(upgrades), 1)
        self.assertNotIn("--set", upgrades[0])
        self.assertEqual(submitted[0]["image"], values["image"])
        self.assertEqual(submitted[0]["frontend"], values["frontend"])
        self.assertEqual(
            at(submitted[0], "extraEnv", "PUBLIC_API_URL"),
            "https://api.candidate.test",
        )
        self.assertEqual(at(submitted[0], "extraEnv", "OIDC_CLIENT_ID"), "agenticos")
        cluster.probe.assert_called_once_with("oidc_probe.py", certificate="local-test-certificate")

    def test_local_integrations_refuse_other_clusters_before_any_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kubeconfig = Path(temporary) / "kubeconfig"
            kubeconfig.touch()
            with patch.object(Cluster, "run", return_value="https://production.example.com") as run:
                with self.assertRaisesRegex(ValueError, "refuse a cluster other than CRC"):
                    Cluster(kubeconfig)
                run.assert_called_once_with("oc", "whoami", "--show-server")

    def test_local_integrations_refuse_namespaces_without_validation_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kubeconfig = Path(temporary) / "kubeconfig"
            kubeconfig.touch()
            with (
                patch.object(
                    Cluster, "run", side_effect=["https://api.crc.testing:6443", '{"metadata": {}}']
                ),
                self.assertRaisesRegex(ValueError, "Refusing namespace not owned"),
            ):
                Cluster(kubeconfig)

    def test_vendor_server_uses_an_unprivileged_named_http_port(self) -> None:
        source = yaml.safe_dump(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "opensandbox-server"},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "server",
                                    "ports": [{"name": "http", "containerPort": 80}],
                                    "readinessProbe": {
                                        "httpGet": {"port": "http", "path": "/health"}
                                    },
                                }
                            ]
                        }
                    }
                },
            }
        )
        document = obj(yaml.safe_load(render_ports(source)))
        container = array(at(document, "spec", "template", "spec", "containers"))[0]
        self.assertEqual(at(array(at(container, "ports"))[0], "containerPort"), 8080)
        self.assertEqual(at(container, "readinessProbe", "httpGet", "port"), "http")
        with self.assertRaisesRegex(ValueError, "upstream HTTP port changed"):
            render_ports(source.replace("containerPort: 80", "containerPort: 8080"))

    def test_openshift_data_fixtures_leave_identity_to_scc(self) -> None:
        for resource in array(fixtures()["items"]):
            if at(resource, "kind") != "Deployment":
                continue
            pod = at(resource, "spec", "template", "spec")
            security = obj(at(pod, "securityContext"))
            self.assertNotIn("fsGroup", security)
            self.assertNotIn("runAsUser", security)
            for container in array(at(pod, "containers")):
                self.assertNotIn("runAsUser", obj(at(container, "securityContext")))
                self.assertFalse(at(container, "securityContext", "allowPrivilegeEscalation"))
                self.assertTrue(at(container, "securityContext", "readOnlyRootFilesystem"))
            for volume in array(at(pod, "volumes")):
                self.assertNotIn("hostPath", obj(volume))

    def test_sandbox_model_fixture_calls_the_exposed_tool_name(self) -> None:
        message, finish = sandbox_message(
            {
                "messages": [{"role": "user", "content": "OPENSHIFT-SANDBOX-WRITE"}],
                "tools": [{"function": {"name": "sandbox__write_file"}}],
            }
        )
        self.assertEqual(finish, "tool_calls")
        call = obj(array(message["tool_calls"])[0])
        self.assertEqual(at(call, "function", "name"), "sandbox__write_file")

    def test_sandbox_model_fixture_preserves_tool_errors(self) -> None:
        message, finish = sandbox_message(
            {"messages": [{"role": "tool", "content": "Error: permission denied"}]}
        )
        self.assertEqual(finish, "stop")
        self.assertEqual(message["content"], "Error: permission denied")

    def test_sandbox_model_fixture_refuses_missing_tools(self) -> None:
        with self.assertRaisesRegex(ValueError, "not exposed"):
            sandbox_message(
                {"messages": [{"role": "user", "content": "OPENSHIFT-SANDBOX-READ"}], "tools": []}
            )

    def test_frontend_receives_oidc_display_settings_without_backend_secrets(
        self,
    ) -> None:
        documents = render(
            "--set-string",
            "frontend.extraEnv.OAUTH_PROVIDERS=oidc",
            "--set-string",
            "frontend.extraEnv.OIDC_DISPLAY_NAME=Company SSO",
            "--set-string",
            "frontend.extraEnv.BACKEND_URL=https://wrong.example.com",
        )
        frontend = next(
            doc
            for doc in documents
            if doc["kind"] == "Deployment"
            and str(at(doc, "metadata", "name")).endswith("-frontend")
        )
        container = obj(array(at(frontend, "spec", "template", "spec", "containers"))[0])
        env = {str(at(item, "name")): at(item, "value") for item in array(container["env"])}
        self.assertEqual(env["OAUTH_PROVIDERS"], "oidc")
        self.assertEqual(env["OIDC_DISPLAY_NAME"], "Company SSO")
        self.assertEqual(env["BACKEND_URL"], "http://smoke-agenticos-api:8000")
        self.assertNotIn("envFrom", container)
        self.assertNotIn("OIDC_CLIENT_SECRET", env)

    def test_workloads_and_migration(self) -> None:
        documents = render()
        self.assertEqual([doc["kind"] for doc in documents].count("Deployment"), 3)
        jobs = [doc for doc in documents if doc["kind"] == "Job"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            at(jobs[0], "metadata", "annotations", "helm.sh/hook"),
            "pre-install,pre-upgrade,pre-rollback",
        )
        self.assertEqual(at(jobs[0], "spec", "backoffLimit"), 0)
        self.assertEqual(at(jobs[0], "spec", "template", "spec", "restartPolicy"), "Never")
        for doc in documents:
            if doc["kind"] not in {"Deployment", "Job"}:
                continue
            pod = obj(at(doc, "spec", "template", "spec"))
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertTrue(at(pod, "securityContext", "runAsNonRoot"))
            self.assertEqual(at(pod, "securityContext", "seccompProfile", "type"), "RuntimeDefault")
            for volume in array(pod["volumes"]):
                if at(volume, "name") == "trust":
                    self.assertEqual(at(volume, "secret", "secretName"), "agenticos-smoke-ca")
                else:
                    self.assertIn("emptyDir", obj(volume))
            for item in array(pod["containers"]):
                container = obj(item)
                self.assertFalse(at(container, "securityContext", "allowPrivilegeEscalation"))
                self.assertTrue(at(container, "securityContext", "readOnlyRootFilesystem"))
                self.assertEqual(at(container, "securityContext", "capabilities", "drop"), ["ALL"])
                self.assertNotIn(":latest", str(container["image"]))
                self.assertIn("resources", container)
                if container["name"] == "frontend":
                    self.assertNotIn("envFrom", container)
                else:
                    self.assertEqual(
                        container["envFrom"],
                        [{"secretRef": {"name": "agenticos-smoke"}}],
                    )
                    env = {
                        str(at(entry, "name")): at(entry, "value")
                        for entry in array(container["env"])
                    }
                    self.assertEqual(env["FILE_STORAGE_BACKEND"], "s3")
                    self.assertEqual(env["ENVIRONMENT"], "production")
                if doc["kind"] == "Deployment":
                    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
                        self.assertIn(probe, container)
                    self.assertEqual(pod["terminationGracePeriodSeconds"], 60)

    def test_openshift_does_not_force_namespace_ids(self) -> None:
        for doc in render("-f", str(ROOT / "charts/agenticos/values-openshift.yaml")):
            if doc["kind"] in {"Deployment", "Job"}:
                pod = obj(at(doc, "spec", "template", "spec"))
                self.assertNotIn("fsGroup", obj(pod["securityContext"]))
                container = array(pod["containers"])[0]
                self.assertNotIn("runAsUser", obj(at(container, "securityContext")))

    def test_digest_pins_both_backend_users(self) -> None:
        digest = "sha256:" + "a" * 64
        for doc in render("--set", f"image.backendDigest={digest}"):
            if doc["kind"] in {"Deployment", "Job"}:
                container = obj(array(at(doc, "spec", "template", "spec", "containers"))[0])
                if container["name"] != "frontend":
                    self.assertEqual(
                        container["image"],
                        f"ghcr.io/vstorm-co/agenticos-backend@{digest}",
                    )

    def test_public_ingress_and_tls(self) -> None:
        docs = render(
            "--set",
            "ingress.enabled=true",
            "--set",
            "ingress.siteHost=app.example.com",
            "--set",
            "ingress.apiHost=api.example.com",
            "--set",
            "ingress.tls[0].secretName=tls",
            "--set",
            "trustedProxy.enabled=true",
            "--set",
            "trustedProxy.namespaceLabels.controller=protected-ingress",
            "--set",
            "trustedProxy.podLabels.controller=trusted",
        )
        ingress = next(doc for doc in docs if doc["kind"] == "Ingress")
        self.assertEqual(len(array(at(ingress, "spec", "rules"))), 2)
        self.assertEqual(at(array(at(ingress, "spec", "tls"))[0], "secretName"), "tls")

    def test_missing_configuration_refused(self) -> None:
        for key in (
            "existingSecret",
            "postgres.host",
            "redis.host",
            "storage.bucket",
            "public.siteUrl",
            "public.apiUrl",
            "public.websocketUrl",
        ):
            with self.subTest(key=key):
                result = subprocess.run(
                    [
                        HELM,
                        "template",
                        "smoke",
                        str(ROOT / "charts/agenticos"),
                        "-f",
                        str(ROOT / "scripts/kubernetes/smoke-values.yaml"),
                        "--set-string",
                        f"{key}=",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(key.replace(".", "/"), result.stderr)

    def test_verified_tls_mounts_the_ca_in_migration_api_and_worker(self) -> None:
        backend_count = 0
        for doc in render(
            "--set",
            "postgres.sslMode=verify-full",
            "--set",
            "trust.existingSecret=external-ca",
            "--set",
            "trust.sslCaKey=combined-ca.crt",
        ):
            if doc["kind"] not in {"Deployment", "Job"}:
                continue
            pod = obj(at(doc, "spec", "template", "spec"))
            container = obj(array(pod["containers"])[0])
            if container["name"] == "frontend":
                continue
            backend_count += 1
            volumes = {str(at(volume, "name")): obj(volume) for volume in array(pod["volumes"])}
            self.assertEqual(at(volumes["trust"], "secret", "secretName"), "external-ca")
            mounts = {
                str(at(mount, "name")): obj(mount) for mount in array(container["volumeMounts"])
            }
            self.assertEqual(mounts["trust"]["mountPath"], "/etc/agenticos/trust")
            self.assertTrue(mounts["trust"]["readOnly"])
            env = {str(at(item, "name")): at(item, "value") for item in array(container["env"])}
            self.assertEqual(env["PGSSLROOTCERT"], "/etc/agenticos/trust/postgres-ca.crt")
            self.assertEqual(env["SSL_CERT_FILE"], "/etc/agenticos/trust/combined-ca.crt")
        self.assertEqual(backend_count, 3)

    def test_unsafe_or_incomplete_settings_are_refused(self) -> None:
        cases = [
            (("--set", "storage.encryption=sse-kms"), "kmsKeyId"),
            (
                ("--set", "postgres.sslMode=verify-full", "--set", "trust.existingSecret="),
                "existingSecret",
            ),
            (
                (
                    "--set",
                    "trust.sslCaKey=private-ca.crt",
                    "--set",
                    "postgres.sslMode=disable",
                    "--set",
                    "trust.existingSecret=",
                ),
                "existingSecret",
            ),
            (("--set", "trustedProxy.enabled=true"), "namespaceLabels"),
            (("--set", "ingress.enabled=true"), "trustedProxy"),
        ]
        for arguments, reason in cases:
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(subprocess.CalledProcessError) as caught,
            ):
                render(*arguments)
            self.assertIn(reason, caught.exception.stderr)
        self.assertTrue(
            render("--set", "storage.encryption=sse-kms", "--set", "storage.kmsKeyId=key-id")
        )

    def test_trusted_forwarding_is_coupled_to_restrictive_network_policies(self) -> None:
        arguments = (
            "--set",
            "trustedProxy.enabled=true",
            "--set",
            "trustedProxy.namespaceLabels.controller=protected-ingress",
            "--set",
            "trustedProxy.podLabels.controller=trusted",
        )
        documents = render(*arguments)
        policies = [doc for doc in documents if doc["kind"] == "NetworkPolicy"]
        self.assertEqual(len(policies), 2)
        for policy in policies:
            ingress = array(at(policy, "spec", "ingress"))
            trusted = array(at(ingress[0], "from"))[0]
            self.assertEqual(
                at(trusted, "namespaceSelector", "matchLabels"), {"controller": "protected-ingress"}
            )
            self.assertEqual(at(trusted, "podSelector", "matchLabels"), {"controller": "trusted"})
            component = at(
                policy, "spec", "podSelector", "matchLabels", "app.kubernetes.io/component"
            )
            self.assertEqual(len(ingress), 2 if component == "api" else 1)
            if component == "api":
                frontend = array(at(ingress[1], "from"))[0]
                self.assertEqual(
                    at(frontend, "podSelector", "matchLabels"),
                    {
                        "app.kubernetes.io/instance": "smoke",
                        "app.kubernetes.io/component": "frontend",
                    },
                )
        for doc in documents:
            if doc["kind"] in {"Deployment", "Job"}:
                container = obj(array(at(doc, "spec", "template", "spec", "containers"))[0])
                if container["name"] != "frontend":
                    env = {
                        str(at(item, "name")): at(item, "value") for item in array(container["env"])
                    }
                    self.assertEqual(env["RATE_LIMIT_TRUST_FORWARDED_FOR"], "true")
        self.assertFalse(any(doc["kind"] == "NetworkPolicy" for doc in render()))

    def test_cors_uses_the_browser_origin_without_a_trailing_slash(self) -> None:
        for doc in render("--set", "public.siteUrl=https://app.example.com/"):
            if doc["kind"] in {"Deployment", "Job"}:
                container = obj(array(at(doc, "spec", "template", "spec", "containers"))[0])
                if container["name"] != "frontend":
                    env = {
                        str(at(item, "name")): at(item, "value") for item in array(container["env"])
                    }
                    self.assertEqual(env["CORS_ORIGINS"], '["https://app.example.com"]')
                    self.assertEqual(env["FRONTEND_URL"], "https://app.example.com")
                    self.assertEqual(env["RATE_LIMIT_TRUST_FORWARDED_FOR"], "false")

    def test_chart_has_no_node_privileges_or_stored_credentials(self) -> None:
        serialized = json.dumps(render()).lower()
        for forbidden in (
            "hostpath",
            "docker.sock",
            "hostnetwork",
            "privileged",
            '"kind": "secret"',
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
