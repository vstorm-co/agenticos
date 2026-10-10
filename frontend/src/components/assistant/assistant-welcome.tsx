"use client";

import type { ReactNode } from "react";
import { BookOpen, Bot, Eye, FileUp, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChatWelcome } from "@/components/chat/chat-welcome";
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
  /** The Architect's face, above the greeting. */
  mark: ReactNode;
  page: PageContext | null;
  onPick: (prompt: string) => void;
}

/**
 * The AI Architect's empty conversation, drawn as `/chat` draws one (#2075):
 * its face, the greeting, what it does, and four ways to start.
 */
export function AssistantWelcome({ greeting, name, mark, page, onPick }: AssistantWelcomeProps) {
  const t = useTranslations("assistantWidget");
  const person = useAuthStore((state) => state.user?.full_name?.split(" ")[0] ?? null);

  const prompt = (tile: Tile["key"]) =>
    tile === "lookAround" && page
      ? t("tiles.lookAround.askOnPage", { title: page.title, path: page.path })
      : t(`tiles.${tile}.ask`);

  return (
    <ChatWelcome
      compact
      mark={mark}
      title={
        greeting ??
        (person
          ? t("greetingNamed", { person, assistant: name })
          : t("greeting", { assistant: name }))
      }
      lead={t("welcomeLead")}
      suggestions={TILES.map(({ key, icon }) => ({
        key,
        icon,
        title: t(`tiles.${key}.label`),
        prompt: prompt(key),
      }))}
      onPick={onPick}
    />
  );
}
