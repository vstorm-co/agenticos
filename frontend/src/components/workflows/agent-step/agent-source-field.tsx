"use client";

import { useTranslations } from "next-intl";
import {
  AgentVersionPicker,
  type AgentVersionRef,
} from "@/components/workflows/pickers/agent-version-picker";
import { isRecord } from "@/components/workflows/property-panel/schema-model";

/** New steps use catalog agents. Existing inline specs remain intact until replaced. */
export function AgentSourceField({
  config,
  error,
  disabled,
  onChange,
}: {
  config: Record<string, unknown>;
  error?: string;
  disabled?: boolean;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslations("workflows");
  const ref = isRecord(config.agent) ? config.agent : {};
  const pin: AgentVersionRef = {
    agent_id: typeof ref.agent_id === "string" ? ref.agent_id : null,
    version_id: typeof ref.version_id === "string" ? ref.version_id : null,
  };
  return (
    <div className="space-y-3">
      {isRecord(config.inline) && (
        <p className="text-muted-foreground text-sm">{t("agentSourceLegacy")}</p>
      )}
      <AgentVersionPicker
        value={pin}
        error={error}
        disabled={disabled}
        onChange={(agent) => {
          const { inline: _inline, agent: _agent, ...rest } = config;
          onChange({ ...rest, agent });
        }}
      />
    </div>
  );
}
