"use client";

import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { AgentEnvironment } from "@/types/agents";

/** Sentinel for "the default environment" - a Select item may not be empty. */
export const DEFAULT_ENV = "__default__";

/**
 * The environment a trigger binds its fires to, said in terms of consequences.
 *
 * A trigger fires with nobody watching, so the moment of choosing here is the
 * only moment anyone reads this. `{name} (v{version})` alone hides the two
 * facts that decide what actually runs at 09:00 tomorrow: whether the
 * environment follows publishes (somebody else's publish silently repoints
 * it), and how far a pinned one is behind the latest publish - the field whose
 * own docstring says it tells "pinned on purpose" from "forgotten". Each row
 * carries both, and the caption under the field says which version the next
 * fire will run.
 */
export function EnvironmentField({
  value,
  onChange,
  environments,
  id = "trigger-environment",
}: {
  value: string;
  onChange: (value: string) => void;
  environments: AgentEnvironment[];
  id?: string;
}) {
  const t = useTranslations("triggers");
  const selected = environments.find((environment) => environment.id === value) ?? null;
  const caption =
    selected === null
      ? t("environmentCaptionDefault")
      : selected.tracks_latest
        ? t("environmentCaptionTracking", { version: selected.version })
        : t("environmentCaptionPinned", { version: selected.version });
  return (
    <FormField label={t("environment")} htmlFor={id} description={caption}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT_ENV}>{t("defaultEnvironment")}</SelectItem>
          {environments.map((environment) => (
            <SelectItem key={environment.id} value={environment.id}>
              <span className="flex items-center gap-2">
                <span>{environment.name}</span>
                <span className="text-muted-foreground text-xs">v{environment.version}</span>
                {environment.tracks_latest ? (
                  <span className="text-muted-foreground text-xs">{t("environmentFollows")}</span>
                ) : environment.behind_by > 0 ? (
                  <span className="text-warning text-xs">
                    {t("environmentBehind", { count: environment.behind_by })}
                  </span>
                ) : null}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
