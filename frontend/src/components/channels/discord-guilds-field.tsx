"use client";

import { useTranslations } from "next-intl";
import { FormField, Textarea } from "@/components/ui";

export function parseDiscordGuilds(value: string): string[] {
  return [...new Set(value.split(/[\s,]+/).filter(Boolean))].sort();
}

export function validDiscordGuilds(value: string): boolean {
  const ids = parseDiscordGuilds(value);
  return ids.length <= 2500 && ids.every((id) => /^[1-9][0-9]{0,19}$/.test(id));
}

export function DiscordGuildsField({
  idPrefix,
  value,
  onChange,
}: {
  idPrefix: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("pages.channels");
  const valid = validDiscordGuilds(value);
  const id = `${idPrefix}-discord-guilds`;
  return (
    <FormField
      htmlFor={id}
      label={t("discordGuilds")}
      description={t("discordGuildsHint")}
      error={valid ? undefined : t("discordGuildsInvalid")}
    >
      <Textarea
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={!valid || undefined}
        autoComplete="off"
        spellCheck={false}
        rows={2}
        className="min-h-11"
      />
    </FormField>
  );
}
