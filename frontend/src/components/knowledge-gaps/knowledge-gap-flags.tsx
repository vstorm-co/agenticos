"use client";

import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle, Checkbox, Label } from "@/components/ui";
import type { KnowledgeGapFlag } from "@/types/knowledge-gaps";

interface KnowledgeGapFlagsProps {
  flags: KnowledgeGapFlag[];
  confirmed: boolean;
  onConfirmed: (confirmed: boolean) => void;
}

/**
 * What in a topic's content may identify somebody, and the confirmation adding
 * it then takes. A document reaches everybody its knowledge base's agents
 * answer, so a number repeated from one person's question is shown to be
 * checked rather than added unseen.
 */
export function KnowledgeGapFlags({ flags, confirmed, onConfirmed }: KnowledgeGapFlagsProps) {
  const t = useTranslations("knowledgeGaps");
  return (
    <Alert variant="warning">
      <ShieldAlert className="h-4 w-4" aria-hidden />
      <AlertTitle>{t("flagsTitle")}</AlertTitle>
      <AlertDescription className="space-y-2">
        <ul className="list-disc pl-5 text-xs">
          {flags.map((flag) => (
            <li key={`${flag.kind}:${flag.value}`}>
              {flag.kind === "shared"
                ? t("flagShared", { value: flag.value })
                : t("flagPersonalData", {
                    category: t(`flagCategories.${flag.value}`),
                    count: flag.count,
                  })}
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-2">
          <Checkbox
            id="knowledge-gap-confirm-identifying"
            checked={confirmed}
            onCheckedChange={(next) => onConfirmed(next === true)}
          />
          <Label htmlFor="knowledge-gap-confirm-identifying" className="text-xs">
            {t("flagsConfirm")}
          </Label>
        </div>
      </AlertDescription>
    </Alert>
  );
}
