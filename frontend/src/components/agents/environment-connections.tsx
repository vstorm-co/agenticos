"use client";

import { useState } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useOrgMcpConnections, useSecrets } from "@/hooks";
import type { AgentEnvironment, EnvironmentConnection } from "@/types/agents";

/** The select value standing for "no test side": the binding is off here. */
const OFF = "off";

interface Option {
  id: string;
  label: string;
  /** What a test side has to match to stand in for this one. */
  match: string;
  /** Whether a run could reach it now; a run treats one it cannot as off. */
  usable: boolean;
}

type Kind = EnvironmentConnection["kind"];

/** What the caller can list, per kind, and how to name an id they cannot. */
function useConnectionOptions() {
  const { connections: servers } = useOrgMcpConnections();
  const { secrets } = useSecrets();
  const options: Record<Kind, Option[]> = {
    mcp: servers.map((server) => ({
      id: server.id,
      label: server.name,
      match: "mcp",
      usable: server.is_enabled && server.authorized,
    })),
    secret: secrets.map((secret) => ({
      id: secret.id,
      label: secret.name,
      match: `${secret.kind}/${secret.purpose ?? "custom"}`,
      usable: true,
    })),
  };
  const label = (kind: Kind, id: string) =>
    options[kind].find((option) => option.id === id)?.label ?? id.slice(0, 8);
  // The server refuses a stand-in of another kind or purpose, and a run treats one it
  // cannot reach as off, so neither is offered as a replacement.
  const standIns = (kind: Kind, productionId: string) => {
    const match = options[kind].find((option) => option.id === productionId)?.match;
    return options[kind].filter(
      (option) => option.id !== productionId && option.match === match && option.usable,
    );
  };
  const unusable = (kind: Kind, id: string) =>
    options[kind].find((option) => option.id === id)?.usable === false;
  return { options, label, standIns, unusable };
}

/**
 * Which bindings a named environment answers with test systems - a sandbox CRM,
 * a test mailbox - so staging, and every eval run in it, never reaches the
 * production one.
 *
 * The list is saved whole on every change, the way the API takes it. An
 * override whose test side was deleted reads "off" and is kept on every save:
 * dropping it would quietly put the environment back on production.
 *
 * Only what the caller can list is offered. An id they cannot see still renders,
 * shortened, rather than as an empty row.
 */
export function EnvironmentConnections({
  environment,
  saving,
  onSave,
}: {
  environment: AgentEnvironment;
  saving: boolean;
  onSave: (connections: EnvironmentConnection[]) => void;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const { label, standIns, unusable } = useConnectionOptions();
  const current = environment.connections;

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">{t("testConnectionsHint")}</p>
      {current.map((connection, index) => {
        const name = label(connection.kind, connection.production_id);
        const offered = standIns(connection.kind, connection.production_id);
        return (
          <div
            key={`${connection.kind}:${connection.production_id}`}
            className="flex items-center gap-2 text-sm"
          >
            <Badge variant="outline">
              {connection.kind === "mcp"
                ? t("testConnectionKindMcp")
                : t("testConnectionKindSecret")}
            </Badge>
            <span className="truncate">{name}</span>
            <ArrowRight className="text-muted-foreground h-3 w-3 shrink-0" aria-hidden />
            <Select
              value={connection.test_id ?? OFF}
              disabled={saving}
              onValueChange={(value) =>
                onSave(
                  current.map((other, at) =>
                    at === index ? { ...other, test_id: value === OFF ? null : value } : other,
                  ),
                )
              }
            >
              <SelectTrigger className="h-8 w-48" aria-label={t("testSideFor", { name })}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={OFF}>{t("bindingOffHere")}</SelectItem>
                {connection.test_id !== null &&
                  !offered.some((option) => option.id === connection.test_id) && (
                    <SelectItem value={connection.test_id}>
                      {label(connection.kind, connection.test_id)}
                    </SelectItem>
                  )}
                {offered.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {connection.test_id !== null && unusable(connection.kind, connection.test_id) && (
              <Badge variant="warning">{t("testSideUnusable")}</Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              disabled={saving}
              aria-label={tc("removeNamed", { name })}
              onClick={() => onSave(current.filter((_, at) => at !== index))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        );
      })}
      <AddTestConnection
        taken={new Set(current.map((c) => `${c.kind}:${c.production_id}`))}
        saving={saving}
        onAdd={(connection) => onSave([...current, connection])}
      />
    </div>
  );
}

function AddTestConnection({
  taken,
  saving,
  onAdd,
}: {
  taken: Set<string>;
  saving: boolean;
  onAdd: (connection: EnvironmentConnection) => void;
}) {
  const t = useTranslations("agents");
  const { options, standIns } = useConnectionOptions();
  const [kind, setKind] = useState<Kind>("mcp");
  const [production, setProduction] = useState("");
  const [test, setTest] = useState("");

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={kind}
        onValueChange={(value) => {
          setKind(value as Kind);
          setProduction("");
          setTest("");
        }}
      >
        <SelectTrigger className="h-8 w-36" aria-label={t("testConnectionKindLabel")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="mcp">{t("testConnectionKindMcp")}</SelectItem>
          <SelectItem value="secret">{t("testConnectionKindSecret")}</SelectItem>
        </SelectContent>
      </Select>
      <Select
        value={production}
        onValueChange={(value) => {
          setProduction(value);
          setTest("");
        }}
      >
        <SelectTrigger className="h-8 w-48" aria-label={t("productionSide")}>
          <SelectValue placeholder={t("productionSide")} />
        </SelectTrigger>
        <SelectContent>
          {options[kind]
            .filter((option) => !taken.has(`${kind}:${option.id}`))
            .map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {option.label}
              </SelectItem>
            ))}
        </SelectContent>
      </Select>
      <Select value={test} disabled={production === ""} onValueChange={setTest}>
        <SelectTrigger className="h-8 w-48" aria-label={t("testSide")}>
          <SelectValue placeholder={t("testSide")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={OFF}>{t("bindingOffHere")}</SelectItem>
          {standIns(kind, production).map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        disabled={production === "" || test === "" || saving}
        onClick={() => {
          onAdd({ kind, production_id: production, test_id: test === OFF ? null : test });
          setProduction("");
          setTest("");
        }}
      >
        <Plus className="h-4 w-4" />
        {t("add")}
      </Button>
    </div>
  );
}
