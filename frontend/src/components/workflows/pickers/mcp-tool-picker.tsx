"use client";

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { useMcpCatalog, usePermissions, useUsableMcpConnections } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { connectionLabel, offeredTools } from "@/lib/mcp-servers";
import {
  testOrgMcpConnection,
  type UsableMcpConnectionRecord,
} from "@/lib/org-mcp-connections-api";
import { qk } from "@/lib/query-keys";
import { Perm } from "@/types/permissions";

export interface McpConnectionPickerProps {
  /** The chosen connection's id, or null for none yet. */
  value: string | null;
  onChange: (connectionId: string | null) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * One of the organization's MCP servers, each with its service's mark.
 *
 * Only the organization's own servers: a workflow's reach cannot depend on whose
 * account starts it, the rule an agent's bindings follow. Listing them needs
 * the right to edit this workflow, which publishing a step needs, so an editor
 * picks one without managing servers; anybody else is told so instead of shown
 * an empty list. Only a manager is offered a way to connect another.
 */
export function McpConnectionPicker(props: McpConnectionPickerProps) {
  const t = useTranslations("workflows");
  const { canRead } = useUsableMcpConnections();
  if (!canRead) {
    return <p className="text-muted-foreground text-xs">{t("pickerMcpNeedsPermission")}</p>;
  }
  return <ConnectionSelect {...props} />;
}

function ConnectionSelect({
  value,
  onChange,
  disabled,
  error,
  connections,
  isLoading,
}: McpConnectionPickerProps & {
  connections?: UsableMcpConnectionRecord[];
  isLoading?: boolean;
}) {
  const t = useTranslations("workflows");
  const { can } = usePermissions();
  const listed = useUsableMcpConnections();
  const { servers: catalog } = useMcpCatalog();
  const all = connections ?? listed.connections ?? [];
  const loading = isLoading ?? listed.isLoading;
  const orphaned = value !== null && !loading && !all.some((one) => one.id === value);
  const caption = t("pickerMcpServerLabel");

  return (
    <div className="space-y-2">
      <Label>{caption}</Label>
      <Select value={value ?? ""} onValueChange={(next) => onChange(next)} disabled={disabled}>
        <SelectTrigger aria-label={caption}>
          <SelectValue placeholder={t("pickerMcpServerPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {all.map((connection) => (
            <SelectItem key={connection.id} value={connection.id}>
              <span className="flex items-center gap-2">
                <McpServerIcon
                  icon={
                    catalog.find(
                      (entry) => entry.key === (connection.catalog_key ?? connection.name),
                    )?.icon
                  }
                  name={connectionLabel(connection)}
                  className="h-4 w-4"
                />
                <span className="truncate">{connectionLabel(connection)}</span>
                {!connection.is_enabled && <Badge variant="secondary">{t("pickerHostOff")}</Badge>}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {all.length === 0 && !loading && (
        <p className="text-muted-foreground text-xs">
          {t("pickerMcpEmpty")}{" "}
          {can(Perm.mcpManage) && (
            <Link href={ROUTES.MCP_SERVERS} className="underline underline-offset-2">
              {t("pickerMcpAdd")}
            </Link>
          )}
        </p>
      )}
      {orphaned && <p className="text-foreground/70 text-xs">{t("pickerMcpOrphaned")}</p>}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}

export interface McpToolFieldProps {
  connectionId: string | null;
  tool: string | null;
  /** The pair as changed; a new server clears the tool, which was the old one's. */
  onChange: (next: { connectionId: string | null; tool: string | null }) => void;
  disabled?: boolean;
  serverError?: string;
  toolError?: string;
}

/**
 * `mcp.call`'s server and tool, as one field: the tool is chosen from what the
 * server offered when it was last tested, and testing again refreshes the list.
 */
export function McpToolField(props: McpToolFieldProps) {
  const t = useTranslations("workflows");
  const { canRead } = useUsableMcpConnections();
  if (!canRead) {
    return <p className="text-muted-foreground text-xs">{t("pickerMcpNeedsPermission")}</p>;
  }
  return <ToolField {...props} />;
}

function ToolField({
  connectionId,
  tool,
  onChange,
  disabled,
  serverError,
  toolError,
}: McpToolFieldProps) {
  const t = useTranslations("workflows");
  const { can } = usePermissions();
  const queryClient = useQueryClient();
  const { connections: listed, isLoading } = useUsableMcpConnections();
  const connections = listed ?? [];
  const [testing, setTesting] = useState(false);
  const connection = connections.find((one) => one.id === connectionId) ?? null;
  const offered = connection === null ? null : offeredTools(connection);
  // A tool the step names but the list no longer has stays a choice, so the
  // select shows what is set rather than going blank.
  const tools =
    offered === null || tool === null || offered.some((one) => one.name === tool)
      ? (offered ?? [])
      : [...offered, { name: tool, description: "" }];
  const caption = t("pickerMcpToolLabel");

  const refresh = async (id: string) => {
    setTesting(true);
    try {
      // Testing probes the server and writes what it offers; only a manager may.
      const result = await testOrgMcpConnection(id);
      await queryClient.invalidateQueries({ queryKey: qk.mcpConnections.all() });
      if (result.error) toast.error(result.error);
    } catch {
      toast.error(t("pickerMcpTestFailed"));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-4">
      <ConnectionSelect
        value={connectionId}
        onChange={(next) => onChange({ connectionId: next, tool: null })}
        disabled={disabled}
        error={serverError}
        connections={connections}
        isLoading={isLoading}
      />
      {connection !== null && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <Label>{caption}</Label>
            {can(Perm.mcpManage) && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 px-2 text-xs"
                onClick={() => void refresh(connection.id)}
                disabled={disabled || testing}
              >
                <RefreshCw aria-hidden className={testing ? "size-3.5 animate-spin" : "size-3.5"} />
                {t("pickerMcpRefresh")}
              </Button>
            )}
          </div>
          <Select
            value={tool ?? ""}
            onValueChange={(next) => onChange({ connectionId, tool: next })}
            disabled={disabled || tools.length === 0}
          >
            <SelectTrigger aria-label={caption}>
              {/* The chosen tool by name alone; its description is for choosing. */}
              <SelectValue placeholder={t("pickerMcpToolPlaceholder")}>
                {tool !== null && <span className="font-mono text-xs">{tool}</span>}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {tools.map((one) => (
                <SelectItem key={one.name} value={one.name}>
                  <span className="flex min-w-0 flex-col items-start">
                    <span className="font-mono text-xs">{one.name}</span>
                    {one.description && (
                      <span className="text-muted-foreground line-clamp-1 text-xs">
                        {one.description}
                      </span>
                    )}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {offered === null && (
            <p className="text-muted-foreground text-xs">
              {t(can(Perm.mcpManage) ? "pickerMcpNeverTested" : "pickerMcpNeverTestedEditor")}
            </p>
          )}
          {toolError !== undefined && <p className="text-destructive text-xs">{toolError}</p>}
        </div>
      )}
    </div>
  );
}

/**
 * The JSON Schema of a tool's arguments, as its server listed it when last
 * tested - what `mcp.call`'s arguments are edited as, one field per argument.
 *
 * Null until a server and tool are chosen, when the server kept none, or for a
 * member who may not edit the workflow: they get the arguments as one object instead.
 * Reads the list the picker holds, through the same cache key.
 */
export function useMcpToolSchema(
  connectionId: string | null,
  tool: string | null,
): Record<string, unknown> | null {
  const { connections } = useUsableMcpConnections(connectionId !== null);
  const connection = (connections ?? []).find((one) => one.id === connectionId);
  const offered = (connection === undefined ? null : offeredTools(connection)) ?? [];
  return offered.find((one) => one.name === tool)?.input_schema ?? null;
}
