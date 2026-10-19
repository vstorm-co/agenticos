"use client";

import { BookOpen, FileSearch, Mail, Sparkles } from "lucide-react";

import { useTranslations } from "next-intl";

import { useAuth } from "@/hooks";

import { ChatWelcome, WelcomeIcon } from "./chat-welcome";

/** The four openers, in order. Their words live in the catalog under `empty.<id>*`. */
const PROMPTS = [
  { icon: FileSearch, id: "docs" },
  { icon: BookOpen, id: "concept" },
  { icon: Mail, id: "email" },
  { icon: Sparkles, id: "brainstorm" },
] as const;

interface ChatEmptyStateProps {
  onPick: (prompt: string) => void;
}

export function ChatEmptyState({ onPick }: ChatEmptyStateProps) {
  const t = useTranslations("chat.empty");
  const { user } = useAuth();
  const firstName = user?.full_name?.split(" ")[0] || user?.email?.split("@")[0];

  return (
    <ChatWelcome
      mark={<WelcomeIcon icon={Sparkles} />}
      title={firstName ? t("greeting", { name: firstName }) : t("greetingAnonymous")}
      lead={t("lead")}
      suggestions={PROMPTS.map((p) => ({
        key: p.id,
        icon: p.icon,
        title: t(`${p.id}Title`),
        prompt: t(`${p.id}Prompt`),
      }))}
      onPick={onPick}
      footer={
        <>
          <kbd className="border-border bg-card rounded px-1.5 py-0.5 font-mono text-xs">⌘K</kbd>
          <span>{t("commandPalette")}</span>
          <span className="text-border">·</span>
          <kbd className="border-border bg-card rounded px-1.5 py-0.5 font-mono text-xs">/</kbd>
          <span>{t("slashCommands")}</span>
        </>
      }
    />
  );
}
