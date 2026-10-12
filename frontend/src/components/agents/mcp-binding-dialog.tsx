"use client";

import { useState } from "react";
import { Plug, Plus, Wrench, X } from "lucide-react";
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
  IconButton,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { cn } from "@/lib/utils";
import type { McpServerRef } from "@/types/agents";

/** A binding through somebody's account - every kind but the platform's own server. */
export type AccountRef = Exclude<McpServerRef, { account: "platform" }>;

interface McpBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  /** Every binding the spec holds for this server, in spec order; empty while unused. */
  bindings: AccountRef[];
  /** Every account the organization holds on the server. */
  connections: OrgMcpConnectionRecord[];
  /** The catalog key, where the catalog knows the server - what each person's own account binds. */
  catalogKey: string | null;
  /** The server's bindings, rebuilt - one callback for every gesture, like the picker's. */
  onChange: (next: AccountRef[]) => void;
  onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  /** Connect another of the organization's accounts; absent outside the catalog. */
  onConnect?: () => void;
  onCheck?: (connectionId: string) => Promise<unknown>;
  disabled?: boolean;
}

/**
 * How this agent uses one MCP server: through which accounts, and which tools.
 *
 * A server can be reached through several accounts at once - the company
 * mailbox and `info@`, both the organization's, or each person's own beside
 * them (#2125) - so the dialog is a list of accounts, each with its own whose,
 * which and tools, and **Add another account** under it. The card on the grid
 * only says whether the agent uses the server; everything about *how* lives
 * here.
 */
export function McpBindingDialog({
  open,
  onOpenChange,
  name,
  bindings,
  connections,
  catalogKey,
  onChange,
  onTools,
  onConnect,
  onCheck,
  disabled,
}: McpBindingDialogProps) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const boundIds = new Set(
    bindings.flatMap((ref) => (ref.account === "organization" ? [ref.connection_id] : [])),
  );
  const free = connections.filter((connection) => !boundIds.has(connection.id));
  const personalBound = bindings.some((ref) => ref.account === "personal");
  const canAddPersonal = catalogKey !== null && !personalBound;

  const replace = (index: number, next: AccountRef) =>
    onChange(bindings.map((ref, at) => (at === index ? next : ref)));
  const remove = (index: number) => onChange(bindings.filter((_, at) => at !== index));
  const organizationRef = (target: OrgMcpConnectionRecord, from?: AccountRef): AccountRef => ({
    account: "organization",
    connection_id: target.id,
    // Carried over: the tools are chosen for the agent, and the account it
    // speaks through is a different question.
    allowed_tools: from?.allowed_tools ?? null,
  });
  const personalRef = (from?: AccountRef): AccountRef | null =>
    catalogKey === null
      ? null
      : {
          account: "personal",
          catalog_key: catalogKey,
          allowed_tools: from?.allowed_tools ?? null,
        };
  const add = () => {
    const next = free[0] ? organizationRef(free[0]) : canAddPersonal ? personalRef() : null;
    if (next) onChange([...bindings, next]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("serverSettingsTitle", { name })}</DialogTitle>
          <DialogDescription>{t("serverSettingsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {bindings.length === 0 ? (
            // Unused yet: choosing whose account binds the server, so a person
            // who opened the card to look can switch it on from here.
            <WhoseAccount
              name={name}
              value={undefined}
              organization={connections[0] !== undefined}
              personal={catalogKey !== null}
              disabled={disabled}
              onChange={(next) => {
                const ref =
                  next === "personal"
                    ? personalRef()
                    : connections[0]
                      ? organizationRef(connections[0])
                      : null;
                if (ref) onChange([ref]);
              }}
            />
          ) : (
            bindings.map((binding, index) => (
              <AccountBlock
                key={binding.account === "personal" ? "personal" : binding.connection_id}
                name={name}
                binding={binding}
                connections={connections}
                choices={
                  binding.account === "organization"
                    ? connections.filter(
                        (option) => option.id === binding.connection_id || !boundIds.has(option.id),
                      )
                    : free
                }
                canBePersonal={
                  catalogKey !== null && (!personalBound || binding.account === "personal")
                }
                removable={bindings.length > 1}
                disabled={disabled}
                onWhose={(whose) => {
                  const next =
                    whose === "personal"
                      ? personalRef(binding)
                      : free[0]
                        ? organizationRef(free[0], binding)
                        : null;
                  if (next) replace(index, next);
                }}
                onConnection={(target) => replace(index, organizationRef(target, binding))}
                onLabels={(labels) =>
                  binding.account === "personal" &&
                  replace(index, { ...binding, account_labels: labels })
                }
                onRemove={() => remove(index)}
                onTools={(probed) => onTools(binding, probed, name)}
                onCheck={onCheck}
              />
            ))
          )}

          {bindings.length > 0 &&
            (free.length > 0 || canAddPersonal ? (
              <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={add}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("addAnotherAccount")}
              </Button>
            ) : (
              onConnect && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={onConnect}
                >
                  <Plug className="mr-1 h-3.5 w-3.5" />
                  {t("connectAnotherAccount")}
                </Button>
              )
            ))}

          {connections.length === 0 && onConnect && (
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

        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {tc("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Whose account: the organization's, or each person's own. */
function WhoseAccount({
  name,
  value,
  organization,
  personal,
  disabled,
  onChange,
}: {
  name: string;
  value: "organization" | "personal" | undefined;
  organization: boolean;
  personal: boolean;
  disabled?: boolean;
  onChange: (next: "organization" | "personal") => void;
}) {
  const t = useTranslations("agents");
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next === "personal" ? "personal" : "organization")}
    >
      <SelectTrigger aria-label={t("accountForServer", { name })}>
        <SelectValue placeholder={t("chooseAccount")} />
      </SelectTrigger>
      <SelectContent>
        {organization && <SelectItem value="organization">{t("organizationsAccount")}</SelectItem>}
        {personal && <SelectItem value="personal">{t("eachPersonsOwnAccount")}</SelectItem>}
      </SelectContent>
    </Select>
  );
}

/** One account the agent reaches the server through: whose, which, and its tools. */
function AccountBlock({
  name,
  binding,
  connections,
  choices,
  canBePersonal,
  removable,
  disabled,
  onWhose,
  onConnection,
  onLabels,
  onRemove,
  onTools,
  onCheck,
}: {
  name: string;
  binding: AccountRef;
  connections: OrgMcpConnectionRecord[];
  /** The organization's accounts this block may name: its own, and the unbound. */
  choices: OrgMcpConnectionRecord[];
  canBePersonal: boolean;
  removable: boolean;
  disabled?: boolean;
  onWhose: (whose: "organization" | "personal") => void;
  onConnection: (target: OrgMcpConnectionRecord) => void;
  onLabels: (labels: string[] | null) => void;
  onRemove: () => void;
  onTools: (probed: OrgMcpConnectionRecord) => void;
  onCheck?: (connectionId: string) => Promise<unknown>;
}) {
  const t = useTranslations("agents");
  const personal = binding.account === "personal";
  const connection = personal
    ? null
    : (connections.find((option) => option.id === binding.connection_id) ?? null);
  // The tools come from an organization connection's probe, so each person's
  // own account is narrowed only where the organization holds one to probe.
  const probed = connection ?? connections[0] ?? null;

  return (
    <div className="border-border space-y-3 rounded-xl border p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <WhoseAccount
            name={name}
            value={binding.account}
            organization={personal ? choices.length > 0 : true}
            personal={canBePersonal}
            disabled={disabled}
            onChange={onWhose}
          />
        </div>
        {removable && (
          <IconButton
            size="icon"
            aria-label={t("removeAccount", { name })}
            disabled={disabled}
            onClick={onRemove}
            className="text-muted-foreground hover:text-destructive shrink-0"
          >
            <X />
          </IconButton>
        )}
      </div>

      {personal ? (
        <>
          <p className="text-muted-foreground text-xs">{t("eachPersonsOwnAccountHint")}</p>
          <AccountLabels
            name={name}
            value={binding.account_labels ?? null}
            disabled={disabled}
            onChange={onLabels}
          />
        </>
      ) : connection && choices.length > 1 ? (
        // Which connection, where there is a choice. The label if somebody set
        // one, and the slug beside it - that is the prefix the model reads.
        <Select
          value={connection.id}
          disabled={disabled}
          onValueChange={(next) => {
            const target = choices.find((option) => option.id === next);
            if (target) onConnection(target);
          }}
        >
          <SelectTrigger aria-label={t("whichAccount", { name })}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {choices.map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {option.label ?? option.name}
                {option.label !== null && (
                  <span className="text-muted-foreground ml-2 font-mono">{option.name}</span>
                )}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        // No choice left - every other account is bound in its own block - but
        // with several on the server, this block still has to say which it is.
        connection &&
        connections.length > 1 && (
          <p className="text-sm">
            {connection.label ?? connection.name}
            {connection.label !== null && (
              <span className="text-muted-foreground ml-2 font-mono text-xs">
                {connection.name}
              </span>
            )}
          </p>
        )
      )}

      {connection && <McpServerHealth connection={connection} onCheck={onCheck} />}

      {probed && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => onTools(probed)}
        >
          <Wrench className="mr-1 h-3.5 w-3.5" />
          {binding.allowed_tools == null
            ? t("everyToolThisServerOffers")
            : t("toolCount", { count: binding.allowed_tools.length })}
        </Button>
      )}
    </div>
  );
}

/**
 * Which of each person's accounts the binding reaches, by label - committed on
 * leaving the field, so a half-typed label never narrows the agent.
 */
function AccountLabels({
  name,
  value,
  disabled,
  onChange,
}: {
  name: string;
  value: string[] | null;
  disabled?: boolean;
  onChange: (labels: string[] | null) => void;
}) {
  const t = useTranslations("agents");
  const [draft, setDraft] = useState((value ?? []).join(", "));
  const id = `account-labels-${name}`;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t("accountLabels")}</Label>
      <Input
        id={id}
        value={draft}
        disabled={disabled}
        placeholder={t("accountLabelsPlaceholder")}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          const labels = draft
            .split(",")
            .map((label) => label.trim())
            .filter((label) => label.length > 0);
          onChange(labels.length > 0 ? labels : null);
        }}
      />
      <p className="text-muted-foreground text-xs">{t("accountLabelsHint", { name })}</p>
    </div>
  );
}
