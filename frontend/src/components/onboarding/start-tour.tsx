"use client";

import { Compass } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useRouter } from "@/lib/locale-navigation";
import { useOnboardingStore } from "@/stores/onboarding-store";

/** Keep the full walkthrough available while a person prepares their workspace. */
export function StartTour() {
  const t = useTranslations("start");
  const router = useRouter();
  const openTour = useOnboardingStore((state) => state.openTour);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        router.push("/dashboard");
        openTour();
      }}
    >
      <Compass size={14} aria-hidden />
      {t("tour")}
    </Button>
  );
}
