"use client";

import { useTranslations } from "next-intl";

import { SYSTEM_AGENT_KINDS } from "@/lib/system-agents";
import { cn } from "@/lib/utils";
import type { SystemAgentKind } from "@/types/agents";

interface SystemAgentKindsProps {
  value: SystemAgentKind;
  onChange: (kind: SystemAgentKind) => void;
}

/** Each system kind can be created, published and selected where it runs. */
export function SystemAgentKinds({ value, onChange }: SystemAgentKindsProps) {
  const t = useTranslations("agents");
  return (
    <div role="radiogroup" aria-label={t("systemKindLabel")} className="space-y-2">
      {SYSTEM_AGENT_KINDS.map((kind) => (
        <button
          key={kind}
          type="button"
          role="radio"
          aria-checked={kind === value}
          onClick={() => onChange(kind)}
          className={cn(
            "w-full rounded-md border p-3 text-left",
            kind === value && "border-primary bg-primary/5",
          )}
        >
          <span className="block text-sm font-medium">{t(`systemKind.${kind}`)}</span>
          <span className="text-muted-foreground block text-xs">{t(`systemKind.${kind}Body`)}</span>
        </button>
      ))}
    </div>
  );
}
