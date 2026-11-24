"""Trust-boundary checks for the rendered Cloud Build triggers."""

from __future__ import annotations

import argparse
import unittest

from ci.render_sync_triggers import render


class RenderSyncTriggerTests(unittest.TestCase):
    def arguments(self) -> argparse.Namespace:
        return argparse.Namespace(
            project="trusted-project",
            region="us-central1",
            repository_resource=(
                "projects/trusted-project/locations/us-central1/connections/github/"
                "repositories/agenticos"
            ),
            validator_account="platform-validator@trusted-project.iam.gserviceaccount.com",
            updater_account="downstream-updater@trusted-project.iam.gserviceaccount.com",
            updater_sha="a" * 40,
            validator_trigger_id="trusted-trigger-123",
            updater_image="us-central1-docker.pkg.dev/trusted-project/ci/updater@sha256:"
            + "b" * 64,
        )

    def test_renderer_pins_source_and_config_and_routes_notifications_without_loop(
        self,
    ) -> None:
        args = self.arguments()
        triggers = render(args)
        push = triggers["platform-push"]
        pr = triggers["platform-pr"]
        updater = triggers["downstream-updater"]

        self.assertEqual(
            push["serviceAccount"],
            "projects/trusted-project/serviceAccounts/platform-validator@trusted-project.iam.gserviceaccount.com",
        )
        self.assertEqual(push["repositoryEventConfig"]["push"]["branch"], "^t3$")
        self.assertEqual(push["gitFileSource"]["revision"], args.updater_sha)
        self.assertEqual(
            push["substitutions"]["_NOTIFICATION_TOPIC"], "t3os-platform-validations"
        )
        self.assertEqual(pr["serviceAccount"], push["serviceAccount"])
        self.assertEqual(pr["gitFileSource"]["revision"], args.updater_sha)
        self.assertEqual(pr["repositoryEventConfig"]["pullRequest"]["branch"], "^t3$")

        self.assertEqual(
            updater["serviceAccount"],
            "projects/trusted-project/serviceAccounts/downstream-updater@trusted-project.iam.gserviceaccount.com",
        )
        self.assertEqual(
            updater["pubsubConfig"]["topic"],
            "projects/trusted-project/topics/t3os-platform-validations",
        )
        self.assertEqual(updater["filter"], '_STATUS == "SUCCESS"')
        self.assertEqual(updater["sourceToBuild"]["ref"], args.updater_sha)
        self.assertEqual(updater["gitFileSource"]["revision"], args.updater_sha)
        self.assertEqual(updater["substitutions"]["_UPDATER_IMAGE"], args.updater_image)
        self.assertNotEqual(
            push["substitutions"]["_NOTIFICATION_TOPIC"], "cloud-builds"
        )

    def test_renderer_refuses_shared_identity_unpinned_source_or_mutable_image(
        self,
    ) -> None:
        args = self.arguments()
        cases = [
            lambda a: setattr(a, "updater_sha", "main"),
            lambda a: setattr(a, "updater_account", a.validator_account),
            lambda a: setattr(a, "updater_image", "latest"),
            lambda a: setattr(
                a,
                "repository_resource",
                "projects/attacker/locations/us-central1/connections/x/repositories/agenticos",
            ),
            lambda a: setattr(a, "validator_trigger_id", "bad/id"),
        ]
        for mutate in cases:
            broken = argparse.Namespace(**vars(args))
            mutate(broken)
            with self.subTest(arguments=vars(broken)), self.assertRaises(ValueError):
                render(broken)

    def test_validation_only_render_does_not_install_downstream_listener(self) -> None:
        args = self.arguments()
        args.validator_trigger_id = None
        args.updater_image = None
        triggers = render(args)
        self.assertEqual(set(triggers), {"platform-push", "platform-pr"})
        self.assertNotIn("downstream-updater", triggers)


if __name__ == "__main__":
    unittest.main()
