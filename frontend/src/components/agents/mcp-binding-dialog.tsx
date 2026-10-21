"use client";

import { useState, type ReactNode } from "react";
import { ExternalLink, Plug, Plus, Settings2, Wrench, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { McpToolChecklist } from "@/components/agents/mcp-tool-checklist";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
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
  Switch,
} from "@/components/ui";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { McpConnectionRecord, McpToolInfo } from "@/lib/mcp-connections-api";
import { ROUTES } from "@/lib/constants";
import { connectionState, MCP_STATE_LABEL } from "@/lib/mcp-servers";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { cn } from "@/lib/utils";
import type { McpApproval, McpServerRef } from "@/types/agents";

/** A binding through somebody's account - every kind but the platform's own server. */
export type AccountRef = Exclude<McpServerRef, { account: "platform" }>;

interface McpBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  /** The catalog's mark and the server's address, for the logo at the top. */
  icon: string | null;
  url: string | null;
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
  /** The reader's own accounts on the server, every one of which a personal binding reaches. */
  ownAccounts?: McpConnectionRecord[];
  /** Disconnect one of the reader's own accounts; absent where nobody may. */
  onDisconnectOwn?: (connection: McpConnectionRecord) => void;
  /** Sign one of them in again, where its grant lapsed or was never finished. */
  onSignInOwn?: (connection: McpConnectionRecord) => void;
  /** Connect the reader's own account; absent outside the catalog. */
  onConnectOwn?: () => void;
  /**
   * Open the connect form for either kind of account, settings unfolded -
   * present for a server that signs in, where **Connect** goes straight to the
   * provider and this is the way to change what it would send.
   */
  onConfigure?: (scope: "organization" | "personal") => void;
  /** Switch the server on or off for this agent, from the dialog's header. */
  onEnabled: (on: boolean) => void;
  disabled?: boolean;
}

/**
 * How this agent uses one MCP server: through whose account, which tools, and
 * which of them wait for a person.
 *
 * Whose account is one switch between the two kinds, with the state of that
 * kind and its next step under it - connected, or a Connect - rather than two
 * tiles whose buttons only some states had. The tools are the reads and the
 * changes as two groups, by their names as a person reads them; the server's
 * own descriptions are a hover away, because some run to a paragraph each.
 *
 * A server can be reached through several accounts at once - the company
 * mailbox and `info@`, both the organization's, or each person's own beside
 * them (#2125) - so further accounts sit under the first, with **Add another
 * account**.
 */
export function McpBindingDialog({
  open,
  onOpenChange,
  name,
  icon,
  url,
  bindings,
  connections,
  catalogKey,
  onChange,
  onTools,
  onConnect,
  personalTools = null,
  ownAccounts = [],
  onDisconnectOwn,
  onSignInOwn,
  onConnectOwn,
  onConfigure,
  onEnabled,
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
  const primary = bindings[0];
  // Which kind the switch shows. Choosing the organization's while it holds no
  // account is a choice with a next step - connect one - so it is the switch's
  // to remember until there is an account to bind.
  const [chosenKind, setChosenKind] = useState<"organization" | "personal" | null>(null);
  const kind =
    chosenKind ?? primary?.account ?? (connections.length > 0 ? "organization" : "personal");

  const replace = (index: number, next: AccountRef) =>
    onChange(bindings.map((ref, at) => (at === index ? next : ref)));
  const remove = (index: number) => onChange(bindings.filter((_, at) => at !== index));
  const organizationRef = (target: OrgMcpConnectionRecord, from?: AccountRef): AccountRef => ({
    account: "organization",
    connection_id: target.id,
    // Carried over: the tools are chosen for the agent, and the account it
    // speaks through is a different question.
    allowed_tools: from?.allowed_tools ?? null,
    approval: from?.approval ?? "none",
  });
  const personalRef = (from?: AccountRef): AccountRef | null =>
    catalogKey === null
      ? null
      : {
          account: "personal",
          catalog_key: catalogKey,
          allowed_tools: from?.allowed_tools ?? null,
          approval: from?.approval ?? "none",
        };
  // Only ever called with something bound: an unused server is switched on, not rebound.
  const rebindPrimary = (next: AccountRef) =>
    onChange(bindings.map((ref) => (ref === primary ? next : ref)));
  const choose = (next: "organization" | "personal") => {
    setChosenKind(next);
    // A server the agent does not use stays unused: picking whose account it
    // would speak through is not switching it on. Binding here made going to
    // the organization's account and back turn the server on by itself.
    if (bindings.length === 0) return;
    if (next === "personal") {
      // The option is disabled where there is no catalog key to bind by.
      const next = primary?.account === "personal" ? null : personalRef(primary);
      if (next) rebindPrimary(next);
    } else if (primary?.account !== "organization") {
      const target = free[0] ?? connections[0];
      if (target) rebindPrimary(organizationRef(target, primary));
    }
  };

  // Where the tools are listed from: the organization's account the agent uses,
  // any of its accounts on the server, or the reader's own. The same tools
  // whichever credential reaches them, so one list chooses for every account.
  const listedBy =
    connections.find((connection) => boundIds.has(connection.id)) ?? connections[0] ?? null;
  const tools = listedBy?.last_tools ?? personalTools;
  const allowed = primary?.allowed_tools ?? null;
  const approval = primary?.approval ?? "none";
  const setTools = (next: string[] | null) =>
    onChange(bindings.map((ref) => ({ ...ref, allowed_tools: next })));
  const setApproval = (next: McpApproval) =>
    onChange(bindings.map((ref) => ({ ...ref, approval: next })));
  // Switched on from here, the server binds the kind the switch above shows -
  // the card's own switch, with no choice made, prefers the organization's.
  const enable = (on: boolean) => {
    const next =
      on && chosenKind === "personal"
        ? personalRef()
        : on && chosenKind === "organization" && connections[0]
          ? organizationRef(connections[0])
          : null;
    if (next) onChange([next]);
    else onEnabled(on);
  };
  const add = () => {
    const next = free[0] ? organizationRef(free[0]) : canAddPersonal ? personalRef() : null;
    if (next) onChange([...bindings, next]);
  };
  const primaryChoices =
    primary?.account === "organization"
      ? connections.filter(
          (option) => option.id === primary.connection_id || !boundIds.has(option.id),
        )
      : [];
  // The organization's account this agent speaks through, else the one it would.
  const current =
    (primary?.account === "organization"
      ? connections.find((option) => option.id === primary.connection_id)
      : undefined) ?? connections[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader className="min-w-0">
          <div className="flex items-center gap-3">
            <span className="border-foreground/10 grid size-10 shrink-0 place-items-center rounded-xl border bg-white">
              <McpServerIcon
                icon={icon}
                name={name}
                url={url}
                className="size-6 text-neutral-900"
              />
            </span>
            <div className="min-w-0 flex-1">
              <DialogTitle>{name}</DialogTitle>
              <DialogDescription>{t("serverInThisAgent")}</DialogDescription>
            </div>
            {/* Beside the title, clear of the close button in the corner. */}
            <Switch
              checked={bindings.length > 0}
              disabled={disabled}
              onCheckedChange={enable}
              aria-label={t("useServerInAgent", { name })}
              className="mr-8 shrink-0"
            />
          </div>
        </DialogHeader>

        {/* The scrollbar sits in the dialog's padding, not over the controls. */}
        <div className={cn(DIALOG_BODY, "min-w-0 space-y-6")}>
          <section className="space-y-2.5">
            <h3 className="text-sm font-medium">{t("whoseAccount")}</h3>
            <div
              role="radiogroup"
              aria-label={t("accountForServer", { name })}
              className="bg-foreground/[0.05] grid grid-cols-2 gap-1 rounded-xl p-1"
            >
              <KindOption
                selected={kind === "personal"}
                disabled={disabled || catalogKey === null}
                onSelect={() => choose("personal")}
              >
                {t("eachPersonsOwnAccount")}
              </KindOption>
              <KindOption
                selected={kind === "organization"}
                disabled={disabled || (connections.length === 0 && !onConnect)}
                onSelect={() => choose("organization")}
              >
                {t("organizationsAccount")}
              </KindOption>
            </div>

            {kind === "personal" ? (
              ownAccounts.length > 0 ? (
                <>
                  <AccountState
                    live
                    // A person may hold any number of their own accounts on a
                    // service, and the agent reaches every one of them (#2125).
                    action={
                      onConnectOwn && (
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={onConnectOwn}
                          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs font-medium disabled:opacity-50"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          {t("connectAnotherOwn")}
                        </button>
                      )
                    }
                  >
                    {t("personalConnectedState", { count: ownAccounts.length })}
                  </AccountState>
                  <OwnAccounts
                    accounts={ownAccounts}
                    disabled={disabled}
                    onDisconnect={onDisconnectOwn}
                    onSignIn={onSignInOwn}
                  />
                </>
              ) : (
                <AccountState
                  action={
                    onConnectOwn && (
                      <>
                        {onConfigure && (
                          <ConfigureLink
                            name={name}
                            disabled={disabled}
                            onClick={() => onConfigure("personal")}
                          />
                        )}
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
                      </>
                    )
                  }
                >
                  {t("personalNotConnectedState")}
                </AccountState>
              )
            ) : current === undefined ? (
              <AccountState
                action={
                  onConnect && (
                    <>
                      {onConfigure && (
                        <ConfigureLink
                          name={name}
                          disabled={disabled}
                          onClick={() => onConfigure("organization")}
                        />
                      )}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={disabled}
                        onClick={onConnect}
                      >
                        <Plug className="mr-1 h-3.5 w-3.5" />
                        {t("connectForOrganization")}
                      </Button>
                    </>
                  )
                }
              >
                {t("organizationHasNone", { name })}
              </AccountState>
            ) : primary?.account === "organization" && primaryChoices.length > 1 ? (
              // A select where there is something to switch to; the account's
              // name where every other one is bound in its own row.
              <WhichOrgAccount
                name={name}
                value={primary.connection_id}
                choices={primaryChoices}
                disabled={disabled}
                onChange={(target) => rebindPrimary(organizationRef(target, primary))}
              />
            ) : (
              <AccountState live>{current.label ?? current.name}</AccountState>
            )}

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

          {(bindings.length > 0 || tools) && (
            <section className="min-w-0 space-y-2.5">
              <h3 className="text-sm font-medium">{t("serverTools")}</h3>
              {tools ? (
                <McpToolChecklist
                  tools={tools}
                  allowed={allowed}
                  onChange={setTools}
                  approval={approval}
                  onApproval={setApproval}
                  prefix={catalogKey}
                  // What the server offers is worth reading before it is
                  // switched on; choosing among it waits until it is.
                  disabled={disabled || bindings.length === 0}
                />
              ) : listedBy ? (
                // The organization's account has never been asked what it offers;
                // asking dials out, which the caller does and then opens the list.
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => primary && onTools(primary, listedBy, name)}
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

        <DialogFooter className="items-center sm:justify-between">
          {bindings.length > 0 ? (
            <Button
              type="button"
              variant="ghost"
              className="text-destructive hover:text-destructive"
              disabled={disabled}
              onClick={() => {
                onChange([]);
                onOpenChange(false);
              }}
            >
              {t("removeFromAgent")}
            </Button>
          ) : (
            <span />
          )}
          <Button type="button" onClick={() => onOpenChange(false)}>
            {tc("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** One half of the whose-account switch. */
function KindOption({
  selected,
  disabled,
  onSelect,
  children,
}: {
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "h-8 truncate rounded-lg px-2 text-[13px] transition-colors disabled:opacity-50",
        selected
          ? "bg-background text-foreground font-medium shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/**
 * The reader's own accounts on the server - which the agent reaches through
 * them, each by its name and the prefix its tools carry, and a way to drop one.
 * Renaming them, or choosing the main one, is the servers page's; it opens
 * in a new tab so the draft here is not lost.
 */
function OwnAccounts({
  accounts,
  disabled,
  onDisconnect,
  onSignIn,
}: {
  accounts: McpConnectionRecord[];
  disabled?: boolean;
  onDisconnect?: (connection: McpConnectionRecord) => void;
  onSignIn?: (connection: McpConnectionRecord) => void;
}) {
  const t = useTranslations("agents");
  const tMcp = useTranslations("mcp");
  // Disconnecting deletes a credential, so it takes a second click on the row.
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <div className="space-y-1.5">
      <ul className="border-foreground/10 divide-foreground/[0.06] divide-y rounded-xl border">
        {accounts.map((account) => {
          const state = connectionState(account);
          return (
            <li key={account.id} className="flex min-w-0 items-center gap-3 px-3 py-2">
              <span
                aria-hidden
                className={cn(
                  "size-1.5 shrink-0 rounded-full",
                  state === "connected"
                    ? "bg-success"
                    : state === "disabled"
                      ? "bg-muted-foreground/35"
                      : "bg-destructive",
                )}
              />
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5 text-[13px]">
                  <span className="truncate">{account.label ?? account.name}</span>
                  {account.is_default && accounts.length > 1 && (
                    <span className="text-muted-foreground bg-foreground/[0.05] shrink-0 rounded-full px-1.5 text-[11px]">
                      {t("ownAccountMain")}
                    </span>
                  )}
                </span>
                <span className="text-muted-foreground block truncate text-xs">
                  {state === "connected"
                    ? t("ownAccountPrefix", { prefix: account.name })
                    : tMcp(MCP_STATE_LABEL[state])}
                </span>
              </span>
              {onSignIn && state === "needs-authorization" && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={disabled}
                  onClick={() => onSignIn(account)}
                >
                  {t("signInOwn")}
                </Button>
              )}
              {onDisconnect &&
                (confirming === account.id ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    disabled={disabled}
                    onClick={() => {
                      setConfirming(null);
                      onDisconnect(account);
                    }}
                  >
                    {t("confirmDisconnectOwn")}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={disabled}
                    onClick={() => setConfirming(account.id)}
                    aria-label={t("disconnectOwnNamed", { name: account.label ?? account.name })}
                  >
                    {t("disconnectOwn")}
                  </Button>
                ))}
            </li>
          );
        })}
      </ul>
      <a
        href={ROUTES.MCP_SERVERS}
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
      >
        {t("manageOwnAccounts")}
        <ExternalLink className="h-3 w-3" aria-hidden />
      </a>
    </div>
  );
}

/** Where the chosen kind of account stands, and its next step at the right. */
function AccountState({
  live = false,
  action,
  children,
}: {
  live?: boolean;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-2">
      <span className="text-muted-foreground flex min-w-0 flex-1 items-center gap-1.5 text-xs">
        <span
          aria-hidden
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            live ? "bg-success" : "bg-muted-foreground/35",
          )}
        />
        <span className="min-w-0">{children}</span>
      </span>
      {action && <span className="flex shrink-0 items-center gap-3">{action}</span>}
    </div>
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

/** **Configure**, as the quiet link beside a connect action rather than a second button. */
function ConfigureLink({
  name,
  disabled,
  onClick,
}: {
  name: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  const tMcp = useTranslations("mcp");
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={tMcp("configureNamed", { name })}
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline disabled:opacity-50"
    >
      <Settings2 className="h-3.5 w-3.5" aria-hidden />
      {tMcp("configure")}
    </button>
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
