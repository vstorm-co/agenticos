"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SectionCard } from "@/components/settings/settings-section";
import { Button, Input, Label } from "@/components/ui";
import { useExternalAgents } from "@/hooks/use-desktop";
import { getErrorMessage } from "@/lib/api-error";

/** A native confirmation reviews the actual argv before registration is saved. */
export function ExternalAgentSettings() {
  const t = useTranslations("desktop.settings.externalAgents");
  const tErrors = useTranslations("errors");
  const { state, save, remove } = useExternalAgents();
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
            { id, name, program, args: argv },
            {
              onSuccess: () => {
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
