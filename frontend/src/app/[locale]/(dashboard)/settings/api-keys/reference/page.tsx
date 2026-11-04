"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { ApiReference } from "@/components/settings/api-reference/api-reference";
import { ROUTES } from "@/lib/constants";

export default function ApiReferencePage() {
  const t = useTranslations("apiReference");
  return (
    <div className="flex flex-1 flex-col space-y-4">
      <Link
        href={ROUTES.SETTINGS_API_KEYS}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        {t("back")}
      </Link>
      <ApiReference />
    </div>
  );
}
