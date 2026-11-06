"use client";

import { SlashCommandsManager } from "@/components/settings/slash-commands-manager";
import { useTranslations } from "next-intl";

export default function SlashCommandsSettingsPage() {
  const t = useTranslations("pages.settings");
  return (
    <div className="flex flex-1 flex-col space-y-6">
      <section className="bg-card border-foreground/[0.07] shadow-card rounded-2xl border">
        <header className="border-foreground/[0.06] border-b px-5 py-4 sm:px-6">
          <h2 className="text-foreground text-sm font-semibold">{t("slashCommands")}</h2>
          <p className="text-muted-foreground mt-1 text-xs">{t("customizeCommandPaletteChat")}</p>
        </header>
        <div className="p-5 sm:p-6">
          <SlashCommandsManager />
        </div>
      </section>
    </div>
  );
}
