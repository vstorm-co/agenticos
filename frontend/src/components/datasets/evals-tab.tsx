"use client";

import { Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { ListCard, ListCardEmpty } from "@/components/ui";

/** The dataset's eval runs: an agent run through its cases and compared with before. */
export function EvalsTab() {
  const t = useTranslations("datasets");
  return (
    <ListCard title={t("evals")} counted={null}>
      <ListCardEmpty icon={Play} title={t("noEvals")} description={t("noEvalsBody")} />
    </ListCard>
  );
}
