"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useSystemAgents } from "@/hooks/use-agents";
import { ROUTES } from "@/lib/constants";
import { SYSTEM_AGENT_KINDS } from "@/lib/system-agents";
import { cn } from "@/lib/utils";
import type { SystemAgentKind } from "@/types/agents";

/**
 * The kinds that can be added. A judge is picked where it is used - a dataset
 * grades with its own - so another one does something; every other kind always
 * runs as the organization's own, so another would never run.
 */
export const ADDABLE_KINDS: ReadonlySet<SystemAgentKind> = new Set(["judge"]);

interface SystemAgentKindsProps {
  value: SystemAgentKind;
  onChange: (kind: SystemAgentKind) => void;
}

/**
 * Which kind of system agent to add, each said in a sentence. A kind that cannot
 * be added says why and links the organization's own, where its model and
 * instructions are changed instead.
 */
export function SystemAgentKinds({ value, onChange }: SystemAgentKindsProps) {
  const t = useTranslations("agents");
  const { groups } = useSystemAgents();
  return (
    <div role="radiogroup" aria-label={t("systemKindLabel")} className="space-y-2">
      {SYSTEM_AGENT_KINDS.map((kind) => {
        const addable = ADDABLE_KINDS.has(kind);
        const own = groups
          .find((group) => group.kind === kind)
          ?.agents.find((agent) => agent.system_key);
        return (
          <div
            key={kind}
            className={cn(
              "rounded-md border p-3",
              kind === value && "border-primary bg-primary/5",
              !addable && "opacity-80",
            )}
          >
            <button
              type="button"
              role="radio"
              aria-checked={kind === value}
              disabled={!addable}
              onClick={() => onChange(kind)}
              className="w-full text-left disabled:cursor-not-allowed"
            >
              <span className="block text-sm font-medium">{t(`systemKind.${kind}`)}</span>
              <span className="text-muted-foreground block text-xs">
                {t(`systemKind.${kind}Body`)}
              </span>
            </button>
            {!addable && (
              <p className="text-muted-foreground mt-1 text-xs">
                {t("systemKindLocked")}{" "}
                {own && (
                  <Link className="underline" href={ROUTES.AGENT_DETAIL(own.id)}>
                    {t("systemKindOpenOwn")}
                  </Link>
                )}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
