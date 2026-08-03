"use client";

import { AlertTriangle, Boxes, Cloud, FileText } from "lucide-react";

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
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

export const SANDBOX_CAPABILITY_ID = "sandbox";

type Backend = "state" | "docker" | "daytona";
type Scope = "run" | "conversation" | "user" | "agent";

interface WorkspaceSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec | undefined;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

const BACKENDS: {
  id: Backend;
  label: string;
  detail: string;
  icon: typeof FileText;
}[] = [
  {
    id: "state",
    label: "Files",
    detail: "Files but no shell, stored here. Works on every deployment.",
    icon: FileText,
  },
  {
    id: "docker",
    label: "Container",
    detail: "Files and a shell, in a container the sandbox service runs.",
    icon: Boxes,
  },
  {
    id: "daytona",
    label: "Daytona",
    detail: "Files and a shell in the cloud, billed to your own account.",
    icon: Cloud,
  },
];

const SCOPES: { id: Scope; label: string; detail: string }[] = [
  { id: "run", label: "Nobody", detail: "A fresh workspace every turn." },
  {
    id: "conversation",
    label: "This conversation",
    detail: "Everyone in the chat, group channels included.",
  },
  {
    id: "user",
    label: "Each person",
    detail: "One workspace per person, across their chats with this agent.",
  },
  {
    id: "agent",
    label: "Everyone using this agent",
    detail: "One shared workspace for the whole organization.",
  },
];

/**
 * The workspace decision, on its own, rather than as one switch among tools.
 *
 * Every other capability is "may this agent do X". This one is "where does this
 * agent keep things, and who else can read them" — four choices with different
 * infrastructure behind them, and one of them shares files between people. A row
 * in the capability picker presents that as the same kind of decision as turning
 * on a chart tool, which it is not.
 *
 * The generated configuration form is suppressed for the same reason. A schema
 * can render an enum; it cannot say that picking one of the values means a
 * colleague will see your uploads.
 */
export function WorkspaceSection({
  definition,
  binding,
  onChange,
  disabled,
}: WorkspaceSectionProps) {
  // A deployment that did not register the capability has nothing to configure,
  // and an empty section reads as something that failed to load.
  if (!definition) return null;

  const enabled = binding?.enabled === true;
  const config = (binding?.config ?? {}) as {
    backend?: Backend;
    session_scope?: Scope;
    runtime?: string | null;
    include_execute?: boolean;
  };
  const backend: Backend = config.backend ?? "state";
  const scope: Scope = config.session_scope ?? "conversation";
  const containerBacked = backend === "docker" || backend === "daytona";

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
      // A runtime names an environment inside a container. Carrying one onto a
      // backend that runs none is refused at publish, so it is cleared here
      // rather than left to fail in a form somebody has already left.
      ...(next === "state" ? { runtime: null } : {}),
    });
  };

  return (
    <div className="space-y-4">
      <fieldset disabled={disabled} className="space-y-2">
        <legend className="sr-only">Workspace</legend>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
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
                {option.label}
              </span>
              <span className="text-muted-foreground text-xs">{option.detail}</span>
            </button>
          ))}
        </div>
      </fieldset>

      {enabled && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="workspace-scope">Who shares it</Label>
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
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                {SCOPES.find((option) => option.id === scope)?.detail}
              </p>
            </div>

            {containerBacked && (
              <div className="space-y-1.5">
                <Label htmlFor="workspace-runtime">Runtime</Label>
                <input
                  id="workspace-runtime"
                  type="text"
                  value={config.runtime ?? ""}
                  disabled={disabled}
                  placeholder="the deployment's default"
                  onChange={(event) => setConfig({ runtime: event.target.value.trim() || null })}
                  className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
                />
                <p className="text-muted-foreground text-xs">
                  An environment your deployment allows. It never names an image — that is the
                  operator&apos;s decision.
                </p>
              </div>
            )}
          </div>

          {/* The warning a schema cannot express. `agent` scope is the one
              setting here that lets one person read another person's files, and
              it ships without a permission of its own - so the consequence is
              made visible instead of gated. */}
          {scope === "agent" && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-xs">
                Everyone who talks to this agent reads and writes the same files. A file one person
                uploads is visible to the rest of the organization. Publishing this is recorded in
                the audit log.
              </p>
            </div>
          )}

          <div className="border-border flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium">Shell commands</p>
              <p className="text-muted-foreground text-xs">
                {backend === "state"
                  ? "The Files workspace has no shell — pair it with Run Python to compute."
                  : "Off removes the shell entirely, rather than asking before each command."}
              </p>
            </div>
            <Switch
              checked={config.include_execute !== false}
              disabled={disabled || backend === "state"}
              aria-label="Allow shell commands"
              onCheckedChange={(checked) => setConfig({ include_execute: checked })}
            />
          </div>

          {binding && (
            <CapabilityDetail
              binding={binding}
              definition={definition}
              onChange={onChange}
              disabled={disabled}
              // The choice above *is* this capability's configuration; the
              // generated form would render the same four fields again.
              hideConfigForm
            />
          )}
        </div>
      )}
    </div>
  );
}
