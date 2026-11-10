"""Render the real chart and enforce deployment and refusal contracts."""

import json
import os
import subprocess
import unittest
from pathlib import Path

import yaml

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
