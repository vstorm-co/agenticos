"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";

export function NotFoundBackButton() {
  const t = useTranslations("layout");
  const router = useRouter();
  return (
    <Button variant="outline" onClick={() => router.back()}>
      {t("goBack")}
    </Button>
  );
}
