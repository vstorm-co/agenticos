"use client";

import { NativeSelect } from "@/components/ui/native-select";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { SectionCard } from "@/components/settings/settings-section";
import { Button, Input, Label } from "@/components/ui";
import { useExternalAgents } from "@/hooks/use-desktop";
import type { ExternalAgent } from "@/lib/desktop/commands";
import { getErrorMessage } from "@/lib/api-error";

/** A native confirmation reviews the actual argv before registration is saved. */
export function ExternalAgentSettings() {
  const t = useTranslations("desktop.settings.externalAgents");
  const tErrors = useTranslations("errors");
  const { state, save, remove } = useExternalAgents();
  const [provider, setProvider] = useState<ExternalAgent["provider"]>("custom");
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [program, setProgram] = useState("");
  const [args, setArgs] = useState("[]");
  const [invalidArgs, setInvalidArgs] = useState(false);
  const error = state.error ?? save.error ?? remove.error;
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <ul className="mb-4 space-y-2">
        {(state.data ?? []).map((agent) => (
          <li key={agent.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0">
              <span className="block truncate font-medium">{agent.name}</span>
              <code className="text-muted-foreground block truncate text-xs">{agent.id}</code>
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={remove.isPending || save.isPending}
              onClick={() => remove.mutate(agent.id)}
              aria-label={t("removeNamed", { name: agent.name })}
            >
              {t("remove")}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          let argv: unknown;
          try {
            argv = JSON.parse(args);
          } catch {
            setInvalidArgs(true);
            return;
          }
          if (
            !Array.isArray(argv) ||
            !argv.every((arg: unknown): arg is string => typeof arg === "string")
          ) {
            setInvalidArgs(true);
            return;
          }
          setInvalidArgs(false);
          save.mutate(
            { provider, id, name, program, args: argv },
            {
              onSuccess: () => {
                setProvider("custom");
                setId("");
                setName("");
                setProgram("");
                setArgs("[]");
              },
            },
          );
        }}
      >
        <div>
          <Label htmlFor="external-agent-provider">{t("provider")}</Label>
          <NativeSelect
            id="external-agent-provider"
            value={provider}
            onChange={(event) => {
              const selected = event.target.value;
              if (
                selected !== "antigravity" &&
                selected !== "cursor" &&
                selected !== "cline" &&
                selected !== "cline_api_key" &&
                selected !== "mistral_vibe" &&
                selected !== "grok" &&
                selected !== "kimi" &&
                selected !== "devin" &&
                selected !== "qwen_subscription" &&
                selected !== "opencode" &&
                selected !== "opencode_go"
              ) {
                setProvider("custom");
                return;
              }
              setProvider(selected);
              setId(selected.replaceAll("_", "-"));
              // i18n-exempt: product names
              const names = {
                antigravity: "Antigravity",
                cursor: "Cursor",
                cline: "Cline",
                cline_api_key: t("clineApi"),
                mistral_vibe: "Mistral Vibe",
                grok: "Grok",
                kimi: "Kimi Code",
                devin: "Devin",
                qwen_subscription: t("qwenSubscription"),
                opencode: "OpenCode",
                opencode_go: "OpenCode Go",
              };
              setName(names[selected]);
              setArgs(
                selected === "devin"
                  ? '["--permission-mode","normal","acp"]'
                  : selected === "qwen_subscription"
                    ? '["--acp","--auth-type=qwen-subscription"]'
                    : selected === "grok"
                      ? '["--no-auto-update","agent","stdio"]'
                      : selected === "mistral_vibe"
                        ? "[]"
                        : selected === "cline" || selected === "cline_api_key"
                          ? '["--acp"]'
                          : '["acp"]',
              );
            }}
          >
            <option value="custom">{t("custom")}</option>
            {/* i18n-exempt: product name */}
            <option value="antigravity">Antigravity</option>
            {/* i18n-exempt: product names */}
            <option value="qwen_subscription">{t("qwenSubscription")}</option>
            {/* i18n-exempt: product name */}
            <option value="devin">Devin</option>
            {/* i18n-exempt: product name */}
            <option value="kimi">Kimi Code</option>
            {/* i18n-exempt: product name */}
            <option value="grok">Grok</option>
            {/* i18n-exempt: product name */}
            <option value="mistral_vibe">Mistral Vibe</option>
            {/* i18n-exempt: product name */}
            <option value="cline">Cline</option>
            <option value="cline_api_key">{t("clineApi")}</option>
            {/* i18n-exempt: product name */}
            <option value="cursor">Cursor</option>
            {/* i18n-exempt: product names */}
            <option value="opencode">OpenCode</option>
            {/* i18n-exempt: product names */}
            <option value="opencode_go">OpenCode Go</option>
          </NativeSelect>
        </div>
        {(provider === "cline" || provider === "cline_api_key") && (
          <p className="text-muted-foreground text-xs">{t("clineHelp")}</p>
        )}
        {provider === "mistral_vibe" && (
          <p className="text-muted-foreground text-xs">{t("vibeHelp")}</p>
        )}
        {provider === "qwen_subscription" && (
          <p className="text-muted-foreground text-xs">{t("qwenHelp")}</p>
        )}
        {provider === "devin" && <p className="text-muted-foreground text-xs">{t("devinHelp")}</p>}
        {provider === "kimi" && <p className="text-muted-foreground text-xs">{t("kimiHelp")}</p>}
        {provider === "grok" && <p className="text-muted-foreground text-xs">{t("grokHelp")}</p>}
        {provider === "cursor" && (
          <p className="text-muted-foreground text-xs">{t("cursorHelp")}</p>
        )}
        {provider === "opencode" && (
          <p className="text-muted-foreground text-xs">{t("opencodeHelp")}</p>
        )}
        {provider === "opencode_go" && (
          <p className="text-muted-foreground text-xs">{t("opencodeGoHelp")}</p>
        )}
        {provider === "antigravity" && (
          <p className="text-muted-foreground text-xs">{t("antigravityHelp")}</p>
        )}
        <div>
          <Label htmlFor="external-agent-id">{t("id")}</Label>
          <Input
            id="external-agent-id"
            value={id}
            onChange={(event) => setId(event.target.value)}
            pattern="[a-z0-9][a-z0-9_-]{0,47}"
            maxLength={48}
            required
            autoCapitalize="none"
            spellCheck={false}
          />
        </div>
        <div>
          <Label htmlFor="external-agent-name">{t("name")}</Label>
          <Input
            id="external-agent-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            required
          />
        </div>
        <div>
          <Label htmlFor="external-agent-program">{t("program")}</Label>
          <Input
            id="external-agent-program"
            value={program}
            onChange={(event) => setProgram(event.target.value)}
            required
            spellCheck={false}
          />
        </div>
        <div>
          <Label htmlFor="external-agent-args">{t("args")}</Label>
          <Input
            id="external-agent-args"
            value={args}
            onChange={(event) => {
              setArgs(event.target.value);
              setInvalidArgs(false);
            }}
            aria-invalid={invalidArgs}
            aria-describedby="external-agent-help"
            required
            spellCheck={false}
          />
        </div>
        <p id="external-agent-help" className="text-muted-foreground text-xs">
          {t("help")}
        </p>
        <Button type="submit" disabled={save.isPending || remove.isPending}>
          {t("save")}
        </Button>
      </form>
      {invalidArgs && (
        <p role="alert" className="text-destructive mt-3 text-sm">
          {t("invalidArgs")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive mt-3 text-sm">
          {getErrorMessage(error, tErrors)}
        </p>
      )}
    </SectionCard>
  );
}
