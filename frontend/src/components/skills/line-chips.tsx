"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { eachAgentOnce, isShown, type ShownAgents } from "./skill-lines";

/**
 * Which agents the page is about: everyone, main, the pinned ones, or one fork.
 *
 * Choosing a fork also points History and Edit at that fork's line. Agents bound only
 * in a draft follow no line, so they have a chip of their own and the lines add up
 * to everyone.
 */
export function LineChips({
  agents,
  forks,
  value,
  onChange,
}: {
  agents: SkillAgentUsage[];
  forks: SkillFork[];
  value: ShownAgents;
  onChange: (next: ShownAgents) => void;
}) {
  const t = useTranslations("skills.page");
  const count = (shown: ShownAgents) =>
    eachAgentOnce(agents.filter((usage) => isShown(usage, shown))).length;
  const choices: { value: ShownAgents; label: string }[] = [
    { value: "all", label: t("show.all", { count: eachAgentOnce(agents).length }) },
    { value: "main", label: t("show.main", { count: count("main") }) },
    { value: "pinned", label: t("show.pinned", { count: count("pinned") }) },
    ...forks.map((fork) => ({
      value: `fork:${fork.id}` as const,
      label: t("show.fork", { name: fork.name, count: count(`fork:${fork.id}`) }),
    })),
    ...(count("draft") > 0
      ? [{ value: "draft" as const, label: t("show.draft", { count: count("draft") }) }]
      : []),
  ];
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label={t("show.label")}
      data-tour="skill-lines"
    >
      {choices.map((choice) => (
        <button
          key={choice.value}
          type="button"
          aria-pressed={value === choice.value}
          onClick={() => onChange(choice.value)}
          className={cn(
            "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
            value === choice.value
              ? "bg-primary text-primary-foreground border-transparent"
              : "text-muted-foreground hover:bg-accent hover:text-foreground border-border",
          )}
        >
          {choice.label}
        </button>
      ))}
    </div>
  );
}
