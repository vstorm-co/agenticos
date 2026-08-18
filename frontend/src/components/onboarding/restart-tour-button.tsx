"use client";

import { usePathname } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton } from "@/components/ui";
import { stripLocale } from "@/lib/active-route";
import { pageHasSteps } from "@/lib/onboarding/tour";
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
 * tour component resolves *which* page from the current path.
 *
 * A page the registry holds no stop for gets no button, because a "?" that opens
 * and closes again is worse than no "?" at all — `/admin/*` and the component
 * playground are the two, both rendering `PageHeader` and neither walked. That
 * check is `pageHasSteps`, which is blind to permissions on purpose: the rest of
 * its dependencies stay a translator, the icon, a pathname and the store's
 * `openPage`, and it carries no permission query, because keeping the button this
 * thin is what lets it live in a header shared by twenty surfaces.
 */
export function RestartTourButton() {
  const t = useTranslations("onboarding");
  const pathname = usePathname();
  const openPage = useOnboardingStore((state) => state.openPage);

  // `?? "/"` because this now renders in twenty headers rather than one page, and
  // `usePathname` is nullable outside a route — an error or not-found boundary
  // would otherwise take the whole header down on `stripLocale`'s first line.
  if (!pageHasSteps(stripLocale(pathname ?? "/"))) return null;

  return (
    <IconButton
      aria-label={t("pageHelp")}
      title={t("pageHelp")}
      // The hint is permanent, deliberately: help on a page is worth offering on
      // every visit, not only until somebody first happens to take it. It stayed
      // in a coloured, slowly breathing state for exactly one press before, which
      // meant the affordance was invisible to anyone who had ever used it once.
      className="onboarding-help-hint"
      onClick={openPage}
    >
      <HelpCircle />
    </IconButton>
  );
}
