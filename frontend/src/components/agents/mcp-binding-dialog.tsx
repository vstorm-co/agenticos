"use client";

import type { ReactNode } from "react";
import { Plug, Plus, Wrench, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { McpToolChecklist } from "@/components/agents/mcp-tool-checklist";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { McpToolInfo } from "@/lib/mcp-connections-api";
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
  /**
   * The server's tools as the reader's own connection last listed them - the
   * catalogue for a server bound only through each person's account, where the
   * organization holds no connection to have listed them.
   */
  personalTools?: McpToolInfo[] | null;
  /** Whether the reader has connected their own account on this server. */
  hasOwnAccount?: boolean;
  /** Connect the reader's own account; absent outside the catalog. */
  onConnectOwn?: () => void;
  disabled?: boolean;
}

/**
 * How this agent uses one MCP server: through which accounts, and which tools -
 * the two questions as two sections, the tools ticked in place.
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
  personalTools = null,
  hasOwnAccount = false,
  onConnectOwn,
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
  // Where the tools are listed from: the organization's account the agent uses,
  // any of its accounts on the server, or the reader's own. The same tools
  // whichever credential reaches them, so one list chooses for every account.
  const listedBy =
    connections.find((connection) => boundIds.has(connection.id)) ?? connections[0] ?? null;
  const tools = listedBy?.last_tools ?? personalTools;
  const allowed = bindings[0]?.allowed_tools ?? null;
  const setTools = (next: string[] | null) =>
    onChange(bindings.map((ref) => ({ ...ref, allowed_tools: next })));
  const primary = bindings[0];
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

        <div className="space-y-5">
          <section className="space-y-2">
            <h3 className="text-sm font-medium">{t("serverAccount")}</h3>
            {/* Whose account, as two choices that each carry their own next step:
                choosing the organization's with none connected connects one, and
                choosing each person's own offers to connect yours. The connect
                buttons used to sit under a select, a second decision after the
                first. */}
            <div
              role="radiogroup"
              aria-label={t("accountForServer", { name })}
              className="grid gap-2 sm:grid-cols-2"
            >
              <KindTile
                selected={primary?.account === "organization"}
                title={t("organizationsAccount")}
                hint={connections.length === 0 ? t("orgAccountConnectHint") : t("orgAccountHint")}
                disabled={disabled || (connections.length === 0 && !onConnect)}
                onSelect={() => {
                  if (primary?.account === "organization") return;
                  if (connections[0] === undefined) {
                    // Nothing to bind yet: connect one, and the Builder binds it.
                    onChange(bindings.filter((ref) => ref !== primary));
                    onConnect?.();
                    return;
                  }
                  const next = organizationRef(free[0] ?? connections[0], primary);
                  onChange(
                    primary ? bindings.map((ref) => (ref === primary ? next : ref)) : [next],
                  );
                }}
              >
                {primary?.account === "organization" &&
                  connections.length > 1 &&
                  (() => {
                    const choices = connections.filter(
                      (option) => option.id === primary.connection_id || !boundIds.has(option.id),
                    );
                    const current = connections.find(
                      (option) => option.id === primary.connection_id,
                    );
                    // A select where there is something to switch to; the account's
                    // name where every other one is bound in its own row.
                    return choices.length > 1 ? (
                      <WhichOrgAccount
                        name={name}
                        value={primary.connection_id}
                        choices={choices}
                        disabled={disabled}
                        onChange={(target) =>
                          onChange(
                            bindings.map((ref) =>
                              ref === primary ? organizationRef(target, primary) : ref,
                            ),
                          )
                        }
                      />
                    ) : (
                      current && (
                        <span className="block text-sm">{current.label ?? current.name}</span>
                      )
                    );
                  })()}
              </KindTile>
              <KindTile
                selected={primary?.account === "personal"}
                title={t("eachPersonsOwnAccount")}
                hint={t("eachPersonsOwnAccountShort")}
                disabled={disabled || catalogKey === null}
                onSelect={() => {
                  if (primary?.account === "personal") return;
                  const next = personalRef(primary);
                  if (next === null) return;
                  onChange(
                    primary ? bindings.map((ref) => (ref === primary ? next : ref)) : [next],
                  );
                }}
              >
                {primary?.account === "personal" && !hasOwnAccount && onConnectOwn && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={disabled}
                    onClick={onConnectOwn}
                  >
                    <Plug className="mr-1 h-3.5 w-3.5" />
                    {t("connectYours")}
                  </Button>
                )}
              </KindTile>
            </div>

            {/* Further accounts the server is reached through (#2125), each a row. */}
            {bindings.slice(1).map((binding, offset) => {
              const index = offset + 1;
              return (
                <AccountBlock
                  key={binding.account === "personal" ? "personal" : binding.connection_id}
                  name={name}
                  binding={binding}
                  connections={connections}
                  choices={
                    binding.account === "organization"
                      ? connections.filter(
                          (option) =>
                            option.id === binding.connection_id || !boundIds.has(option.id),
                        )
                      : free
                  }
                  canBePersonal={
                    catalogKey !== null && (!personalBound || binding.account === "personal")
                  }
                  removable
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
                  onRemove={() => remove(index)}
                />
              );
            })}

            {primary !== undefined && (free.length > 0 || canAddPersonal) && (
              <button
                type="button"
                disabled={disabled}
                onClick={add}
                className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs font-medium disabled:opacity-50"
              >
                <Plus className="h-3.5 w-3.5" />
                {t("addAnotherAccount")}
              </button>
            )}
          </section>

          {bindings.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-medium">{t("serverTools")}</h3>
              {tools ? (
                <McpToolChecklist
                  tools={tools}
                  allowed={allowed}
                  onChange={setTools}
                  disabled={disabled}
                />
              ) : listedBy ? (
                // The organization's account has never been asked what it offers;
                // asking dials out, which the caller does and then opens the list.
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => bindings[0] && onTools(bindings[0], listedBy, name)}
                >
                  <Wrench className="mr-1 h-3.5 w-3.5" />
                  {t("loadTools")}
                </Button>
              ) : (
                <p className="text-muted-foreground text-xs">
                  {t("toolsAfterConnecting", { name })}
                </p>
              )}
            </section>
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
  onRemove,
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
  onRemove: () => void;
}) {
  const t = useTranslations("agents");
  const personal = binding.account === "personal";
  const connection = personal
    ? null
    : (connections.find((option) => option.id === binding.connection_id) ?? null);
  return (
    <div className="space-y-2">
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
          <p className="text-muted-foreground text-xs">{t("eachPersonsOwnAccountShort")}</p>
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
    </div>
  );
}

/** One answer to "whose account": a tile with what it means, and its next step under it. */
function KindTile({
  selected,
  title,
  hint,
  disabled,
  onSelect,
  children,
}: {
  selected: boolean;
  title: string;
  hint: string;
  disabled?: boolean;
  onSelect: () => void;
  children?: ReactNode;
}) {
  return (
    <div
      role="radio"
      aria-checked={selected}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      // A click on a control inside the tile - the account select, Connect
      // yours - is that control's, not a choice of the tile.
      onClick={(event) => {
        if (disabled || (event.target as HTMLElement).closest("button, a, input")) return;
        onSelect();
      }}
      onKeyDown={(event) => {
        if (!disabled && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "focus-visible:ring-ring space-y-2 rounded-xl border p-3 text-left transition-colors outline-none focus-visible:ring-2",
        selected
          ? "border-foreground bg-accent"
          : "border-foreground/12 hover:bg-foreground/[0.03] cursor-pointer",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      <span className="block text-sm font-medium">{title}</span>
      <span className="text-muted-foreground block text-xs leading-snug">{hint}</span>
      {children}
    </div>
  );
}

/** Which of the organization's accounts, where it holds several on the server. */
function WhichOrgAccount({
  name,
  value,
  choices,
  disabled,
  onChange,
}: {
  name: string;
  value: string;
  choices: OrgMcpConnectionRecord[];
  disabled?: boolean;
  onChange: (target: OrgMcpConnectionRecord) => void;
}) {
  const t = useTranslations("agents");
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        const target = choices.find((option) => option.id === next);
        if (target) onChange(target);
      }}
    >
      <SelectTrigger size="sm" aria-label={t("whichAccount", { name })}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {choices.map((option) => (
          <SelectItem key={option.id} value={option.id}>
            {option.label ?? option.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
