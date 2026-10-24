"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgentsOfKind } from "@/hooks/use-agents";
import { ROUTES } from "@/lib/constants";
import type { SystemAgentKind } from "@/types/agents";

interface ChoiceProps {
  kind: SystemAgentKind;
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

/** Load alternatives only when the person opens this optional configuration. */
export function SystemAgentChoice(props: ChoiceProps) {
  const t = useTranslations("agents");
  const [expanded, setExpanded] = useState(false);
  return (
    <details
      aria-label={t(`systemKind.${props.kind}`)}
      className="rounded-md border p-3 text-sm"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="cursor-pointer font-medium">{t(`systemKind.${props.kind}`)}</summary>
      {expanded && <SystemAgentSelect {...props} />}
    </details>
  );
}

function SystemAgentSelect({ kind, value, onChange, disabled = false }: ChoiceProps) {
  const t = useTranslations("agents");
  const id = useId();
  const { agents, isLoading, error } = useAgentsOfKind(kind);
  const picked =
    value === null
      ? agents.find((agent) => agent.system_key != null)
      : agents.find((agent) => agent.id === value);
  return (
    <div className="mt-3 space-y-2">
      <FormField htmlFor={id} label={t("systemChoice.label")}>
        <Select
          value={value ?? "default"}
          onValueChange={(next) => onChange(next === "default" ? null : next)}
          disabled={disabled || isLoading || error !== null}
        >
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">{t("systemChoice.default")}</SelectItem>
            {agents
              .filter((agent) => agent.system_key == null)
              .map((agent) => (
                <SelectItem
                  key={agent.id}
                  value={agent.id}
                  disabled={agent.current_version_id === null || agent.status === "archived"}
                >
                  {agent.name}
                  {agent.current_version_id === null ? ` · ${t("systemChoice.unpublished")}` : ""}
                </SelectItem>
              ))}
            {value !== null && picked === undefined && (
              <SelectItem value={value} disabled>
                {t("systemChoice.missing")}
              </SelectItem>
            )}
          </SelectContent>
        </Select>
      </FormField>
      {error !== null && (
        <p role="alert" className="text-destructive text-xs">
          {t("systemChoice.loadFailed")}
        </p>
      )}
      {picked && (
        <p className="text-muted-foreground text-xs">
          <Link className="underline" href={ROUTES.AGENT_DETAIL(picked.id)}>
            {picked.name}
          </Link>
          {picked.published_model && (
            <span className="font-mono"> · {picked.published_model.label}</span>
          )}
        </p>
      )}
      <p className="text-muted-foreground text-xs">{t("systemChoice.hint")}</p>
    </div>
  );
}
