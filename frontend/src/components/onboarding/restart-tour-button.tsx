"use client";

import { HelpCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton } from "@/components/ui";
// The specific module, not the `@/stores` barrel: PageHeader renders this on
// every dashboard page, and importing through the barrel would make every test
// that mocks `@/stores` (many do, partially) also have to stub this store.
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * Replays the walkthrough. Rendered by `PageHeader`, so it sits at the top of
 * every page — a persistent help affordance rather than a control wired into
 * each page by hand.
 *
 * Deliberately the whole of its dependencies: a translator, the icon, and the
 * store's `restart`. It carries neither the permission query nor the first-run
 * machinery, both of which belong to the modal — which is also where the step
 * list stays permission-filtered. Keeping this button that thin is what lets it
 * live in a header shared by twenty surfaces without dragging the router and a
 * dozen queries into each of their tests.
 */
export function RestartTourButton() {
  const t = useTranslations("onboarding");
  const restart = useOnboardingStore((state) => state.restart);

  return (
    <IconButton aria-label={t("restart")} title={t("restart")} onClick={restart}>
      <HelpCircle />
    </IconButton>
  );
}
