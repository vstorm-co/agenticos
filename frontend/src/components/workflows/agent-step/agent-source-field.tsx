"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Copy, Pencil, Save } from "lucide-react";

import {
  AgentVersionPicker,
  type AgentVersionRef,
} from "@/components/workflows/pickers/agent-version-picker";
import { Button, Tabs, TabsList, TabsTrigger } from "@/components/ui";
import { AvatarFace } from "@/components/ui/avatar-face";
import { useAgents, useAgentVersion, useModelProviders } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { isRecord } from "@/components/workflows/property-panel/schema-model";
import type { AgentSpec } from "@/types/agents";

import { InlineAgentDialog } from "./inline-agent-dialog";

/** The spec a new agent configured in a step starts from. */
export function blankSpec(name: string): AgentSpec {
  return {
    name,
    instructions: "",
    model_profile_id: null,
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
  };
}

function pinOf(value: unknown): AgentVersionRef {
  const ref = isRecord(value) ? value : {};
  return {
    agent_id: typeof ref["agent_id"] === "string" ? ref["agent_id"] : null,
    version_id: typeof ref["version_id"] === "string" ? ref["version_id"] : null,
  };
}

/**
 * Which agent an `agent.run` step asks: one from the catalog, pinned at a
 * version, or one configured right here and versioned with the workflow.
 *
 * The two are `agent` and `inline` on the step's config and exactly one is set,
 * so switching mode writes one and drops the other. Each side offers the way to
 * the other: a catalog agent's configuration can be copied in to adjust, and an
 * agent configured here can be saved to the catalog for other workflows and
 * people to use.
 */
export function AgentSourceField({
  config,
  stepName,
  error,
  disabled,
  onChange,
}: {
  config: Record<string, unknown>;
  /** What a new agent configured here is called until it is named. */
  stepName: string;
  error?: string;
  disabled?: boolean;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslations("workflows");
  const inline = isRecord(config["inline"]) ? (config["inline"] as unknown as AgentSpec) : null;
  const [editing, setEditing] = useState(false);
  const pin = pinOf(config["agent"]);
  const { version } = useAgentVersion(pin.agent_id, pin.version_id);

  const withSource = (source: { agent?: unknown; inline?: AgentSpec }) => {
    const { agent: _agent, inline: _inline, ...rest } = config;
    return { ...rest, ...source };
  };

  return (
    <div className="space-y-3">
      <Tabs
        value={inline === null ? "catalog" : "inline"}
        onValueChange={(mode) =>
          onChange(
            mode === "inline"
              ? withSource({ inline: blankSpec(stepName) })
              : withSource({ agent: { agent_id: null, version_id: null } }),
          )
        }
      >
        <TabsList>
          <TabsTrigger value="catalog" disabled={disabled}>
            {t("agentSourceCatalog")}
          </TabsTrigger>
          <TabsTrigger value="inline" disabled={disabled}>
            {t("agentSourceInline")}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {inline === null ? (
        <div className="space-y-2">
          <AgentVersionPicker
            value={pin}
            onChange={(agent) => onChange(withSource({ agent }))}
            disabled={disabled}
            error={error}
          />
          {version !== undefined && (
            <Button
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => onChange(withSource({ inline: version.spec }))}
            >
              <Copy className="size-3.5" aria-hidden />
              {t("agentSourceCopyIn")}
            </Button>
          )}
        </div>
      ) : (
        <InlineAgentCard
          spec={inline}
          error={error}
          disabled={disabled}
          onEdit={() => setEditing(true)}
        />
      )}

      {inline !== null && (
        <InlineAgentDialog
          open={editing}
          spec={inline}
          onOpenChange={setEditing}
          onSave={(spec) => {
            onChange(withSource({ inline: spec }));
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}

/** An agent configured in a step, at a glance: who it is, its model and its reach. */
function InlineAgentCard({
  spec,
  error,
  disabled,
  onEdit,
}: {
  spec: AgentSpec;
  error?: string;
  disabled?: boolean;
  onEdit: () => void;
}) {
  const t = useTranslations("workflows");
  const tErrors = useTranslations("errors");
  const { profiles } = useModelProviders();
  const { create } = useAgents({ enabled: false });
  const model = profiles.find((profile) => profile.id === spec.model_profile_id);

  const saveAsAgent = async () => {
    try {
      const agent = await create.mutateAsync({ spec });
      toast.success(t("agentSourceSaved", { name: agent.name }), {
        action: <Link href={ROUTES.AGENT_DETAIL(agent.id)}>{t("agentSourceOpenSaved")}</Link>,
      });
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors));
    }
  };

  return (
    <div className="border-border space-y-3 rounded-xl border p-3">
      <div className="flex items-center gap-3">
        <span className="size-9 shrink-0" aria-hidden>
          <AvatarFace seed={spec.name} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{spec.name}</p>
          <p className="text-muted-foreground truncate text-xs">
            {model?.label ?? t("inlineAgentNoModel")}
            {" · "}
            {t("inlineAgentReach", {
              capabilities: spec.capabilities.length,
              servers: spec.mcp_servers.length,
            })}
          </p>
        </div>
      </div>
      {spec.instructions.trim() !== "" && (
        <p className="text-muted-foreground line-clamp-2 text-xs">{spec.instructions}</p>
      )}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled} onClick={onEdit}>
          <Pencil className="size-3.5" aria-hidden />
          {t("inlineAgentConfigure")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || create.isPending}
          onClick={() => void saveAsAgent()}
        >
          <Save className="size-3.5" aria-hidden />
          {t("agentSourceSaveAsAgent")}
        </Button>
      </div>
    </div>
  );
}
