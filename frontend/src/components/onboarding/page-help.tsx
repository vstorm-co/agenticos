"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { ContextHelp } from "@/components/ui/context-help";
import { stripLocale } from "@/lib/active-route";
import { pageHasSteps } from "@/lib/onboarding/tour";
import { useOnboardingStore } from "@/stores/onboarding-store";

/** One entry point for the page explanation and its guided walkthrough. */
export function PageHelp({ description }: { description?: ReactNode }) {
  const pathname = usePathname();
  const t = useTranslations("onboarding");
  const openPage = useOnboardingStore((state) => state.openPage);
  const hasTour = pageHasSteps(stripLocale(pathname ?? "/"));
  if (!description && !hasTour) return null;
  return (
    <ContextHelp action={hasTour ? { label: t("pageHelp"), onClick: openPage } : undefined}>
      {description}
    </ContextHelp>
  );
}
