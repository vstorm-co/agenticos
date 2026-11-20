"use client";

import { useTranslations } from "next-intl";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { Agent } from "@/types/agents";
import type { RoomLeadPolicy } from "@/types/room-routing";

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
  leadPolicy,
  askLead,
  onAskLead,
}: {
  agents: readonly Agent[];
  value: string | null;
  onChange: (id: string | null) => void;
  disabled: boolean;
  leadPolicy?: RoomLeadPolicy;
  askLead: boolean;
  onAskLead: () => void;
}) {
  const t = useTranslations("chat.teamRoom");
  const routing = useTranslations("chat.roomRouting");
  return (
    <Select
      value={askLead ? "lead" : (value ?? "team")}
      onValueChange={(next) =>
        next === "lead" ? onAskLead() : onChange(next === "team" ? null : next)
      }
      disabled={disabled}
    >
      <SelectTrigger aria-label={t("responder")} className="h-9 max-w-60 text-xs">
        <SelectValue placeholder={t("chooseResponder")} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="team">{t("humanOnly")}</SelectItem>
        {(leadPolicy?.can_ask || askLead) && (
          <SelectItem value="lead" disabled={!leadPolicy?.can_ask}>
            {leadPolicy?.lead
              ? routing("askLeadNamed", { name: leadPolicy.lead.name })
              : routing("askLead")}
          </SelectItem>
        )}
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            {t("askAgent", { name: agent.name })}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
