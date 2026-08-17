"use client";

import { useSyncExternalStore } from "react";
import { HelpCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton } from "@/components/ui";
import {
  hasUsedPageHelp,
  hasUsedPageHelpOnServer,
  markPageHelpUsed,
  subscribeToPageHelp,
} from "@/lib/onboarding/help-hint";
// The specific module, not the `@/stores` barrel: PageHeader renders this on
// every dashboard page, and importing through the barrel would make every test
// that mocks `@/stores` (many do, partially) also have to stub this store.
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * Replays the current page's tips. Rendered by `PageHeader`, so it sits at the
 * top of every page — a persistent help affordance rather than a control wired
 * into each page by hand.
 *
 * It opens the tour in `"page"` mode, which shows only the highlights that live
 * on the page the reader is on, unchained from the rest of the walkthrough; the
 * tour component resolves *which* page from the current path. Deliberately the
 * whole of its dependencies: a translator, the icon, and the store's `openPage`.
 * It carries neither the permission query nor the path lookup, both of which
 * belong to the tour component — keeping this button that thin is what lets it
 * live in a header shared by twenty surfaces without dragging the router and a
 * dozen queries into each of their tests.
 */
export function RestartTourButton() {
  const t = useTranslations("onboarding");
  const openPage = useOnboardingStore((state) => state.openPage);
  // The flag lives in `localStorage`, which the server has no copy of, so it is
  // read through the hook built for exactly that: the server renders "used" (no
  // pulse in the HTML) and the browser corrects it as it hydrates. `markPageHelpUsed`
  // notifies, so every header on screen stops at the first press, not just this one.
  const used = useSyncExternalStore(subscribeToPageHelp, hasUsedPageHelp, hasUsedPageHelpOnServer);

  return (
    <IconButton
      aria-label={t("pageHelp")}
      title={t("pageHelp")}
      className={used ? undefined : "onboarding-help-hint"}
      onClick={() => {
        markPageHelpUsed();
        openPage();
      }}
    >
      <HelpCircle />
    </IconButton>
  );
}
