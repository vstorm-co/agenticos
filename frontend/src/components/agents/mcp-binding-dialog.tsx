"use client";

import { Plug, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";

import { McpServerHealth } from "@/components/agents/mcp-server-health";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpServerRef } from "@/types/agents";

interface McpBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  /** What the spec binds now, or null while the agent does not use the server. */
  binding: McpServerRef | null;
  /** Every account the organization holds on the server. */
  connections: OrgMcpConnectionRecord[];
  /** The one the binding names, else the first. */
  connection: OrgMcpConnectionRecord | null;
  /** Whether each person's own account can be bound - the catalog knows the server. */
  personalBindable: boolean;
  onBindOrganization: (target: OrgMcpConnectionRecord) => void;
  onBindPersonal: () => void;
  onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  /** Connect the organization's account, where it has none; absent outside the catalog. */
  onConnect?: () => void;
  onCheck?: (connectionId: string) => Promise<unknown>;
  disabled?: boolean;
}

/**
 * How this agent uses one MCP server: whose account, which one, which tools.
 *
 * Opened by switching the server on, and from its card. The card says whether
 * the agent uses the server; everything about *how* lives here, so the grid
 * stays a grid of servers rather than of forms.
 */
export function McpBindingDialog({
  open,
  onOpenChange,
  name,
  binding,
  connections,
  connection,
  personalBindable,
  onBindOrganization,
  onBindPersonal,
  onTools,
  onConnect,
  onCheck,
  disabled,
}: McpBindingDialogProps) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const personal = binding?.account === "personal";
  const account = binding === null ? undefined : personal ? "personal" : "organization";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("serverSettingsTitle", { name })}</DialogTitle>
          <DialogDescription>{t("serverSettingsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Whose account. Choosing one binds the server, so a person who
              opened the card to look can switch it on from here too. */}
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("accountForServer", { name })}</p>
            <Select
              value={account}
              disabled={disabled}
              onValueChange={(next) =>
                next === "personal"
                  ? onBindPersonal()
                  : connection && onBindOrganization(connection)
              }
            >
              <SelectTrigger aria-label={t("accountForServer", { name })}>
                <SelectValue placeholder={t("chooseAccount")} />
              </SelectTrigger>
              <SelectContent>
                {connection && (
                  <SelectItem value="organization">{t("organizationsAccount")}</SelectItem>
                )}
                {personalBindable && (
                  <SelectItem value="personal">{t("eachPersonsOwnAccount")}</SelectItem>
                )}
              </SelectContent>
            </Select>
            {personal && (
              <p className="text-muted-foreground text-xs">{t("eachPersonsOwnAccountHint")}</p>
            )}
            {connection === null && onConnect && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={onConnect}
              >
                <Plug className="mr-1 h-3.5 w-3.5" />
                {t("connectOrganizationAccount")}
              </Button>
            )}
          </div>

          {/* Which connection, where the organization holds more than one. The
              label if somebody set one, and the slug beside it - that is the
              prefix the model reads. */}
          {!personal && connections.length > 1 && connection && (
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("whichAccount", { name })}</p>
              <Select
                value={connection.id}
                disabled={disabled}
                onValueChange={(next) => {
                  const target = connections.find((option) => option.id === next);
                  if (target) onBindOrganization(target);
                }}
              >
                <SelectTrigger aria-label={t("whichAccount", { name })}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {connections.map((option) => (
                    <SelectItem key={option.id} value={option.id}>
                      {option.label ?? option.name}
                      {option.label !== null && (
                        <span className="text-muted-foreground ml-2 font-mono">{option.name}</span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {binding && !personal && connection && (
            <McpServerHealth connection={connection} onCheck={onCheck} />
          )}

          {/* The tools come from an organization connection's probe, so a binding
              to each person's own account is narrowed only where the organization
              holds a connection to the same server. */}
          {binding && connection && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => onTools(binding, connection, name)}
            >
              <Wrench className="mr-1 h-3.5 w-3.5" />
              {binding.allowed_tools == null
                ? t("everyToolThisServerOffers")
                : t("toolCount", { count: binding.allowed_tools.length })}
            </Button>
          )}
        </div>

        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {tc("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
