"use client";

import { useTranslations } from "next-intl";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { Agent } from "@/types/agents";

/** Room requests run on the server, without a person's local or subscription context. */
export function roomResponders(agents: readonly Agent[]): Agent[] {
  return agents.filter(
    (agent) =>
      agent.status === "published" &&
      agent.can_run &&
      !agent.local_workspace &&
      !agent.local_coding_agent &&
      !agent.personal_coding_harness,
  );
}

export function TeamRoomResponder({
  agents,
  value,
  onChange,
  disabled,
}: {
  agents: readonly Agent[];
  value: string | null;
  onChange: (id: string | null) => void;
  disabled: boolean;
}) {
  const t = useTranslations("chat.teamRoom");
  return (
    <Select
      value={value ?? "team"}
      onValueChange={(next) => onChange(next === "team" ? null : next)}
      disabled={disabled}
    >
      <SelectTrigger aria-label={t("responder")} className="h-9 max-w-60 text-xs">
        <SelectValue placeholder={t("chooseResponder")} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="team">{t("humanOnly")}</SelectItem>
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            {t("askAgent", { name: agent.name })}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
