"use client";

import { SlashCommandsManager } from "@/components/settings/slash-commands-manager";
import { useTranslations } from "next-intl";

export default function SlashCommandsSettingsPage() {
  const t = useTranslations("pages.settings");
  return (
    <div className="space-y-6">
      <section className="border-border bg-card rounded-xl border">
        <header className="border-border border-b px-5 py-4">
          <h2 className="text-foreground text-sm font-semibold">{t("slashCommands")}</h2>
          <p className="text-muted-foreground mt-1 text-xs">{t("customizeCommandPaletteChat")}</p>
        </header>
        <div className="px-5 py-5">
          <SlashCommandsManager />
        </div>
      </section>
    </div>
  );
}
