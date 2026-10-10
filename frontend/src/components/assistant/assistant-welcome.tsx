"use client";

import { BookOpen, Bot, Eye, FileUp, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAuthStore } from "@/stores";

export interface PageContext {
  path: string;
  title: string;
}

interface Tile {
  key: "build" | "documents" | "lookAround" | "recipes";
  icon: LucideIcon;
}

const TILES: readonly Tile[] = [
  { key: "build", icon: Bot },
  { key: "documents", icon: FileUp },
  { key: "lookAround", icon: Eye },
  { key: "recipes", icon: BookOpen },
];

interface AssistantWelcomeProps {
  greeting: string | null;
  name: string;
  page: PageContext | null;
  onPick: (prompt: string) => void;
}

/**
 * What an empty conversation with the AI Architect shows (#2063): a greeting by
 * name and four large tiles, so the first message is a click rather than a blank
 * box somebody has to know what to type into.
 */
export function AssistantWelcome({ greeting, name, page, onPick }: AssistantWelcomeProps) {
  const t = useTranslations("assistantWidget");
  const person = useAuthStore((state) => state.user?.full_name?.split(" ")[0] ?? null);

  const prompt = (tile: Tile["key"]) =>
    tile === "lookAround" && page
      ? t("tiles.lookAround.askOnPage", { title: page.title, path: page.path })
      : t(`tiles.${tile}.ask`);

  return (
    <div className="mx-auto w-full max-w-md space-y-5 px-2 py-6">
      <p className="text-foreground text-lg font-semibold">
        {greeting ??
          (person
            ? t("greetingNamed", { person, assistant: name })
            : t("greeting", { assistant: name }))}
      </p>
      <div className="grid grid-cols-2 gap-2">
        {TILES.map(({ key, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => onPick(prompt(key))}
            className="border-border hover:bg-foreground/[0.04] flex flex-col items-start gap-2 rounded-xl border p-3 text-left transition-colors"
          >
            <Icon className="text-muted-foreground h-5 w-5" aria-hidden />
            <span className="text-sm leading-snug font-medium">{t(`tiles.${key}.label`)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
