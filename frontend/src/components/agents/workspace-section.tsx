"use client";

import { AlertTriangle, Boxes, FileText } from "lucide-react";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useSandboxConnections, useSandboxPolicy } from "@/hooks";
import { cn } from "@/lib/utils";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

export const SANDBOX_CAPABILITY_ID = "sandbox";

type Backend = "state" | "service";
type Scope = "run" | "conversation" | "channel" | "user" | "agent";

interface WorkspaceSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec | undefined;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * Two tiles, not four.
 *
 * Docker and Daytona used to be separate choices here, which asked an agent
 * author a question they cannot answer: *where* sandboxes run is a property of
 * the connection an operator registered, and picking the kind separately from
 * the host made it possible to pick two things that disagree. Naming the
 * connection is naming the kind.
 */
const BACKENDS: {
  id: Backend;
  /** Catalog key for this backend's name; its sentence is the same key plus `Detail`. */
  words: string;
  icon: typeof FileText;
}[] = [
  { id: "state", words: "backendState", icon: FileText },
  { id: "service", words: "backendService", icon: Boxes },
];

const SCOPES: { id: Scope; words: string }[] = [
  { id: "run", words: "scopeRun" },
  { id: "conversation", words: "scopeConversation" },
  { id: "channel", words: "scopeChannel" },
  { id: "user", words: "scopeUser" },
  { id: "agent", words: "scopeAgent" },
];

/** Which connection this binding will actually run on, spec or default. */
function resolvedConnection(
  connections: readonly SandboxConnectionRecord[],
  connectionId: string | null,
): SandboxConnectionRecord | undefined {
  if (connectionId !== null)
    return connections.find((connection) => connection.id === connectionId);
  return connections.find((connection) => connection.is_default);
}

/**
 * The workspace decision, on its own, rather than as one switch among tools.
 *
 * Every other capability is "may this agent do X". This one is "where does this
 * agent keep things, and who else can read them" — choices with different
 * infrastructure behind them, and one of them shares files between people. A row
 * in the capability picker presents that as the same kind of decision as turning
 * on a chart tool, which it is not.
 *
 * The generated configuration form is suppressed for the same reason. A schema
 * can render an enum; it cannot say that picking one of the values means a
 * colleague will see your uploads, or that the runtime list has to come from a
 * host that may be switched off.
 */
export function WorkspaceSection({
  definition,
  binding,
  onChange,
  disabled,
}: WorkspaceSectionProps) {
  const t = useTranslations("agents");
  const { connections, error: connectionsError } = useSandboxConnections();

  // A deployment that did not register the capability has nothing to configure,
  // and an empty section reads as something that failed to load.
  if (!definition) return null;

  const enabled = binding?.enabled === true;
  const config = (binding?.config ?? {}) as {
    backend?: Backend;
    connection_id?: string | null;
    session_scope?: Scope;
    runtime?: string | null;
    include_execute?: boolean;
  };
  const backend: Backend = config.backend ?? "state";
  const scope: Scope = config.session_scope ?? "conversation";
  const connectionId = config.connection_id ?? null;
  const connection = resolvedConnection(connections, connectionId);

  const setConfig = (patch: Record<string, unknown>) => {
    if (!binding) return;
    onChange({ ...binding, config: { ...binding.config, ...patch } });
  };

  const chooseBackend = (next: Backend) => {
    // Enablement is the switch above, the same one every capability has. There
    // is no "None" tile: a tile that turns the capability off would be a second
    // control for a decision that already has one, and the two would disagree
    // the moment somebody used the wrong one.
    setConfig({
      backend: next,
      // A runtime names an environment inside a container and a connection names
      // the host it runs on. Carrying either onto the stored workspace is
      // refused at publish, so both are cleared here rather than left to fail in
      // a form somebody has already left.
      ...(next === "state" ? { runtime: null, connection_id: null } : {}),
    });
  };

  return (
    <div className="space-y-4">
      <fieldset disabled={disabled} className="space-y-2">
        <legend className="sr-only">{t("workspace")}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {BACKENDS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => chooseBackend(option.id)}
              aria-pressed={backend === option.id}
              className={cn(
                "flex flex-col gap-1 rounded-xl border px-3 py-3 text-left transition-colors",
                backend === option.id
                  ? "border-foreground/25 bg-accent"
                  : "hover:bg-accent/50 border-border",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <option.icon className="h-3.5 w-3.5" />
                {t(`${option.words}Label`)}
              </span>
              <span className="text-muted-foreground text-xs">{t(`${option.words}Detail`)}</span>
            </button>
          ))}
        </div>
      </fieldset>

      {enabled && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="workspace-scope">{t("whoSharesByDefault")}</Label>
              <Select
                value={scope}
                disabled={disabled}
                onValueChange={(value) => setConfig({ session_scope: value })}
              >
                <SelectTrigger id="workspace-scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCOPES.map((option) => (
                    <SelectItem key={option.id} value={option.id}>
                      {t(`${option.words}Label`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                {t(`${SCOPES.find((option) => option.id === scope)?.words ?? "scopeRun"}Detail`)}{" "}
                Each channel this agent is published to can override it.
              </p>
            </div>

            {backend === "service" && (
              <ConnectionField
                connections={connections}
                connectionId={connectionId}
                error={connectionsError}
                disabled={disabled}
                onChange={(next) => setConfig({ connection_id: next, runtime: null })}
              />
            )}
          </div>

          {backend === "service" && (
            <RuntimeField
              connection={connection}
              runtime={config.runtime ?? null}
              disabled={disabled}
              onChange={(next) => setConfig({ runtime: next })}
            />
          )}

          {/* The warning a schema cannot express. `agent` scope is the one
              setting here that lets one person read another person's files, and
              it ships without a permission of its own - so the consequence is
              made visible instead of gated. */}
          {scope === "agent" && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-xs">{t("everyoneWhoTalksAgent")}</p>
            </div>
          )}

          <div className="border-border flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium">{t("shellCommands")}</p>
              <p className="text-muted-foreground text-xs">
                {backend === "state" ? t("filesWorkspaceHasNo") : t("offRemovesShellEntirely")}
              </p>
            </div>
            <Switch
              checked={config.include_execute !== false}
              disabled={disabled || backend === "state"}
              aria-label={t("allowShellCommands")}
              onCheckedChange={(checked) => setConfig({ include_execute: checked })}
            />
          </div>

          {binding && (
            <CapabilityDetail
              binding={binding}
              definition={definition}
              onChange={onChange}
              disabled={disabled}
              // The choices above *are* this capability's configuration; the
              // generated form would render the same fields again.
              hideConfigForm
            />
          )}
        </div>
      )}
    </div>
  );
}

interface ConnectionFieldProps {
  connections: readonly SandboxConnectionRecord[];
  connectionId: string | null;
  error: string | null;
  disabled?: boolean;
  onChange: (connectionId: string | null) => void;
}

/**
 * Which registered host this agent runs on.
 *
 * "Whatever is default" is a real choice and is offered as one: an agent that
 * follows the organization's default keeps working when the operator retires a
 * host, and pinning one is for the agent that genuinely needs *that* host.
 *
 * An organization with none registered is the case worth spelling out. Publishing
 * is refused for it, and being told here beats being told by a publish error.
 */
function ConnectionField({
  connections,
  connectionId,
  error,
  disabled,
  onChange,
}: ConnectionFieldProps) {
  const t = useTranslations("agents");
  const usable = connections.filter((connection) => connection.is_active);

  return (
    <div className="space-y-1.5">
      <Label htmlFor="workspace-connection">{t("runs2")}</Label>
      <Select
        value={connectionId ?? "default"}
        disabled={disabled || usable.length === 0}
        onValueChange={(value) => onChange(value === "default" ? null : value)}
      >
        <SelectTrigger id="workspace-connection">
          <SelectValue placeholder={t("noSandboxConnectionRegistered")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="default">{t("whicheverDefault")}</SelectItem>
          {usable.map((connection) => (
            <SelectItem key={connection.id} value={connection.id}>
              {connection.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {usable.length === 0 ? (
        <p className="text-destructive text-xs">{error ?? t("organizationHasRegisteredNo")}</p>
      ) : (
        <p className="text-muted-foreground text-xs">{t("hostOperatorRegisteredCredential")}</p>
      )}
    </div>
  );
}

interface RuntimeFieldProps {
  connection: SandboxConnectionRecord | undefined;
  runtime: string | null;
  disabled?: boolean;
  onChange: (runtime: string | null) => void;
}

/**
 * Which environment the container starts in, offered as what the service allows.
 *
 * This was a free-text field, and free text here is a promise nothing keeps: an
 * alias the service does not know is accepted by the form, published, and then
 * refused on the agent's first tool call. The allowlist is read from the service
 * on demand rather than stored, because it is that service's boot configuration
 * and a copy would be wrong the first time an operator restarted it.
 *
 * A host that cannot be reached says so instead of offering an empty list -
 * "no runtimes" and "no answer" are different problems and only one of them is
 * the author's.
 */
function RuntimeField({ connection, runtime, disabled, onChange }: RuntimeFieldProps) {
  const t = useTranslations("agents");
  const { policy, isLoading, error } = useSandboxPolicy(connection?.id ?? null);
  const runtimes = policy?.runtimes ?? [];
  const known = runtimes.some((entry) => entry.alias === runtime);

  return (
    <div className="max-w-sm space-y-1.5">
      <Label htmlFor="workspace-runtime">{t("runtime")}</Label>
      <Select
        value={runtime ?? "default"}
        disabled={disabled || runtimes.length === 0}
        onValueChange={(value) => onChange(value === "default" ? null : value)}
      >
        <SelectTrigger id="workspace-runtime">
          <SelectValue placeholder={isLoading ? t("askingService") : t("connectionSDefault")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="default">
            {connection?.default_runtime ?? t("serviceSOwnDefault")}
          </SelectItem>
          {runtimes.map((entry) => (
            <SelectItem key={entry.alias} value={entry.alias}>
              {entry.alias}
              {entry.mem_limit === null ? "" : ` · ${entry.mem_limit}`}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {error !== null && (
        <p className="text-destructive text-xs">{t("runtimesUnreadable", { error })}</p>
      )}

      {error === null && runtime !== null && !known && !isLoading && runtimes.length > 0 && (
        <p className="text-destructive text-xs">
          This connection no longer allows <span className="font-mono">{runtime}</span>
          {t("pickOneDoesAgent")}
        </p>
      )}

      {error === null && runtimes.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {runtimes.find((entry) => entry.alias === runtime)?.description ||
            t("whatServiceAllowsNever")}
        </p>
      )}
    </div>
  );
}
