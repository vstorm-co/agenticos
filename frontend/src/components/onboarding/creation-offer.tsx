"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { canOfferFlow, FLOWS } from "@/lib/onboarding/flows";
import { qk } from "@/lib/query-keys";
import type { McpCatalog } from "@/types/mcp";
// The specific module, not the `@/stores` barrel — this mounts on every
// dashboard page through `OnboardingFlows`, and the barrel would drag this store
// into every test that partially mocks `@/stores`.
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * The "Create X? [Yes, guide me] [Not now]" prompt that ends a section's "?"
 * walk (and follows the first-run tour, for the agent).
 *
 * It renders whatever flow the store is offering; accepting starts that flow,
 * declining records nothing — asking for help is not the same as finishing
 * onboarding, and a decline the reader can change their mind about is a decline
 * worth nothing to persist. The permission is checked here as well as at the
 * point the offer is made, so a stale offer can never point the reader at a
 * create the server would refuse them.
 *
 * A `ConfirmDialog` rather than bespoke chrome: it is the platform's yes/no, so
 * the offer reads like every other confirmation rather than a second dialect of
 * one.
 */
export function CreationOffer() {
  const t = useTranslations("onboarding");
  const offer = useOnboardingStore((state) => state.offer);
  const openFlow = useOnboardingStore((state) => state.openFlow);
  const dismissOffer = useOnboardingStore((state) => state.dismissOffer);
  const { can } = usePermissions();
  const queryClient = useQueryClient();

  if (offer === null || !canOfferFlow(FLOWS[offer], can)) return null;
  // The MCP catalog is compiled into the deployment; empty, there is nothing to
  // connect, and the walk that ends on this offer had no servers to spotlight
  // either. Read the cache the MCP page already filled — no fetch of this always-
  // mounted component's own — so the offer falls away rather than opening a flow
  // with an empty catalog to pick from.
  if (
    offer === "create-mcp" &&
    queryClient.getQueryData<McpCatalog>(qk.mcpServers.catalog())?.items.length === 0
  ) {
    return null;
  }

  return (
    <ConfirmDialog
      open
      onOpenChange={(next) => {
        if (!next) dismissOffer();
      }}
      title={t(`offer.${offer}.title`)}
      description={t(`offer.${offer}.body`)}
      confirmLabel={t("offer.accept")}
      cancelLabel={t("offer.decline")}
      onConfirm={() => openFlow(offer)}
    />
  );
}
