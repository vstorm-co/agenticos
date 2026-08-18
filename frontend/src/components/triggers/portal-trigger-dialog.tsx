"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  MarkdownEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useAgentEnvironments, useAgents } from "@/hooks";
import { usePortalTargets } from "@/hooks/use-portal-targets";
import { useTriggers } from "@/hooks/use-triggers";
import { useAgentSelectionStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { PortalCatalogEntry } from "@/types/portals";
import type { TriggerCreate, TriggerCreated } from "@/types/triggers";

/** Sentinel for "the default environment" - a Select item may not be empty. */
const DEFAULT_ENV = "__default__";

/** The field label for a portal's target kind, as a fixed key. */
function targetLabelKey(targetKind: string | null): string {
  switch (targetKind) {
    case "repo":
      return "targetRepo";
    case "channel":
      return "targetChannel";
    default:
      return "targetGeneric";
  }
}

interface PortalTriggerDialogProps {
  portal: PortalCatalogEntry;
  /** The shared connected account, or null for a manual portal that needs none. */
  connection: McpConnectionRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Building an event trigger from a portal preset, the friendly path.
 *
 * Two tabs rather than a raw source-and-secret form: **Event** picks a ready-made
 * preset, **Configure** points it at a target, an agent and a message. The server
 * fills the source, the filter and the signing secret from the preset - the
 * payload carries only which portal, which preset, the connected account and the
 * target - so nothing here mints or shows a secret. On a manual-delivery result
 * the webhook URL is shown to paste into the provider; on an auto result the
 * platform has already registered the hook and there is nothing left to do.
 */
export function PortalTriggerDialog({
  portal,
  connection,
  open,
  onOpenChange,
}: PortalTriggerDialogProps) {
  const t = useTranslations("portals");
  const tt = useTranslations("triggers");

  const { agents } = useAgents();
  const defaultAgentId = useAgentSelectionStore((state) => state.defaultAgentId);
  const runnable = agents.filter((agent) => agent.status === "published");
  const [pickedAgentId, setPickedAgentId] = useState("");
  const effectiveAgentId =
    pickedAgentId ||
    (runnable.find((agent) => agent.id === defaultAgentId) ?? runnable[0])?.id ||
    "";

  const { create } = useTriggers(effectiveAgentId || null);
  const { environments } = useAgentEnvironments(effectiveAgentId || null);
  const namedEnvironments = environments.filter((environment) => !environment.is_default);

  const [step, setStep] = useState<"preset" | "configure">("preset");
  const [presetKey, setPresetKey] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [environmentId, setEnvironmentId] = useState(DEFAULT_ENV);
  const [target, setTarget] = useState("");
  const [created, setCreated] = useState<TriggerCreated | null>(null);

  const preset = portal.presets.find((entry) => entry.key === presetKey) ?? null;
  const needsTarget = portal.target_kind !== null && (preset?.target_required ?? false);
  const { targets, isLoading: targetsLoading } = usePortalTargets(
    needsTarget && connection ? portal.key : null,
    needsTarget && connection ? connection.id : null,
  );

  function choosePreset(key: string) {
    setPresetKey(key);
    setStep("configure");
  }

  async function submit() {
    if (preset === null || effectiveAgentId === "") return;
    const payload: TriggerCreate = {
      prompt,
      name: name.trim() || null,
      trigger_type: "event",
      portal_key: portal.key,
      preset_key: preset.key,
      environment_id: environmentId === DEFAULT_ENV ? null : environmentId,
      ...(connection ? { connection_id: connection.id } : {}),
      ...(needsTarget && target.trim() ? { target: target.trim() } : {}),
    };
    try {
      const result = await create.mutateAsync(payload);
      setCreated(result);
    } catch {
      // The hook toasts the server's refusal; the dialog stays open so nothing
      // typed is lost.
    }
  }

  const canSubmit =
    preset !== null &&
    effectiveAgentId !== "" &&
    prompt.trim().length > 0 &&
    (!needsTarget || target.trim().length > 0) &&
    !create.isPending;

  if (created !== null) {
    const manual = created.delivery_mode === "manual";
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{manual ? tt("createdTitle") : t("registeredTitle")}</DialogTitle>
            <DialogDescription>
              {manual ? t("manualResultDescription") : t("registeredDescription")}
            </DialogDescription>
          </DialogHeader>
          {manual && created.webhook_url && <WebhookField url={created.webhook_url} />}
          {manual && created.reveal_secret && <SecretField secret={created.reveal_secret} />}
          <DialogFooter>
            <Button onClick={() => onOpenChange(false)}>{tt("done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("dialogTitle", { portal: portal.name })}</DialogTitle>
          <DialogDescription>{tt("createDescription")}</DialogDescription>
        </DialogHeader>

        <Tabs value={step} onValueChange={(next) => setStep(next as "preset" | "configure")}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="preset">{t("presetTab")}</TabsTrigger>
            <TabsTrigger value="configure" disabled={preset === null}>
              {t("configureTab")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="preset" className="space-y-2">
            {portal.presets.map((entry) => {
              const active = entry.key === presetKey;
              return (
                <button
                  key={entry.key}
                  type="button"
                  onClick={() => choosePreset(entry.key)}
                  aria-pressed={active}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-md border p-3 text-left transition-colors",
                    active
                      ? "border-foreground/30 bg-accent"
                      : "border-input hover:border-foreground/30",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{entry.label}</p>
                    <p className="text-muted-foreground text-xs">{entry.description}</p>
                  </div>
                  {active && <Check className="text-foreground mt-0.5 h-4 w-4 shrink-0" />}
                </button>
              );
            })}
          </TabsContent>

          <TabsContent value="configure" className="space-y-4">
            {needsTarget && (
              <FormField label={t(targetLabelKey(portal.target_kind))} htmlFor="portal-target">
                {targets.length > 0 ? (
                  <Select value={target} onValueChange={setTarget}>
                    <SelectTrigger id="portal-target">
                      <SelectValue placeholder={t("targetPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {targets.map((entry) => (
                        <SelectItem key={entry.id} value={entry.id}>
                          {entry.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="portal-target"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    placeholder={t("targetFreeText")}
                    disabled={targetsLoading}
                  />
                )}
              </FormField>
            )}

            <FormField label={tt("agent")} htmlFor="portal-agent">
              <Select
                value={effectiveAgentId}
                onValueChange={(next) => {
                  setPickedAgentId(next);
                  // A named environment belongs to one agent; carrying the
                  // previous agent's choice across would be refused on create.
                  setEnvironmentId(DEFAULT_ENV);
                }}
              >
                <SelectTrigger id="portal-agent">
                  <SelectValue placeholder={tt("chooseAgent")} />
                </SelectTrigger>
                <SelectContent>
                  {runnable.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>

            <div className="space-y-1.5">
              <Label htmlFor="portal-prompt">{tt("prompt")}</Label>
              <MarkdownEditor
                id="portal-prompt"
                label={tt("prompt")}
                value={prompt}
                onChange={setPrompt}
                placeholder={tt("promptPlaceholder")}
                rows={6}
                describedBy="portal-prompt-desc"
              />
              <p id="portal-prompt-desc" className="text-muted-foreground text-xs leading-relaxed">
                {tt("promptHelp")}
              </p>
            </div>

            <FormField label={tt("nameLabel")} htmlFor="portal-name" description={tt("nameHelp")}>
              <Input
                id="portal-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={tt("namePlaceholder")}
                maxLength={120}
              />
            </FormField>

            {namedEnvironments.length > 0 && (
              <FormField label={tt("environment")} htmlFor="portal-environment">
                <Select value={environmentId} onValueChange={setEnvironmentId}>
                  <SelectTrigger id="portal-environment">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_ENV}>{tt("defaultEnvironment")}</SelectItem>
                    {namedEnvironments.map((environment) => (
                      <SelectItem key={environment.id} value={environment.id}>
                        {environment.name} (v{environment.version})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tt("cancel")}
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {tt("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The webhook URL to paste into the provider, with a copy button. */
function WebhookField({ url }: { url: string }) {
  const t = useTranslations("triggers");
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  return (
    <div className="space-y-1">
      <Label htmlFor="portal-webhook">{t("webhookUrl")}</Label>
      <div className="flex gap-2">
        <Input id="portal-webhook" value={url} readOnly className="flex-1 font-mono text-xs" />
        <Button type="button" variant="outline" onClick={copy}>
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("webhookHelp")}</p>
    </div>
  );
}

/**
 * The reveal-once signing secret, shown only on a manual-delivery create.
 *
 * The platform could not register the webhook, so the user wires their own relay
 * and this secret is what signs each delivery. It is returned exactly once - never
 * on a read - so the copy is offered here with a warning that it will not be shown
 * again.
 */
function SecretField({ secret }: { secret: string }) {
  const t = useTranslations("triggers");
  const tp = useTranslations("portals");
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(secret);
    setCopied(true);
  }

  return (
    <div className="space-y-1">
      <Label htmlFor="portal-secret">{tp("secretLabel")}</Label>
      <div className="flex gap-2">
        <Input id="portal-secret" value={secret} readOnly className="flex-1 font-mono text-xs" />
        <Button type="button" variant="outline" onClick={copy}>
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{tp("secretRevealNote")}</p>
    </div>
  );
}
