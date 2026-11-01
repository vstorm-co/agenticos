"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Checkbox } from "@/components/ui/checkbox";
import { ContextHelp } from "@/components/ui/context-help";
import { useDeviceLink, useDeviceStatus, useLocalSkills } from "@/hooks/use-desktop";
import { SKILL_SOURCES, type SkillSource } from "@/lib/desktop/commands";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";

const FOLDERS: Record<SkillSource, string> = {
  agents: "~/.agents/skills",
  claude: "~/.claude/skills",
  codex: "~/.codex/skills",
};

/**
 * Whether this chat may use the skills and `AGENTS.md` already on this computer (#2576).
 *
 * Off for every new chat, and per source: a person who keeps Claude Code's skills
 * and Codex's may want only one, or only what is in AgenticOS. The files are read
 * in place - nothing is copied or synced - and the app does the reading, so the
 * computer has to be linked first.
 */
export function LocalSkillsControl() {
  const t = useTranslations("chat.controls.workOn.skills");
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const chosen = useWorkOnStore((state) => state.skillsFor(conversationId));
  const setSkills = useWorkOnStore((state) => state.setSkills);
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { data: skills = [] } = useLocalSkills();
  const toggle = useMutation({
    mutationFn: async (next: SkillSource[]) =>
      next.length === 0 || device?.linked === true || (await link.mutateAsync()).linked,
    onSuccess: (linked, next) => {
      if (linked) setSkills(conversationId, next);
    },
  });
  const hidden = skills.filter((skill) => skill.shadowed_by !== null).length;
  return (
    <div className="border-foreground/10 mt-4 border-t pt-4">
      <div className="mb-2 flex items-center gap-1">
        <p className="text-foreground/85 text-[13px] font-medium">{t("title")}</p>
        <ContextHelp>{t("help")}</ContextHelp>
      </div>
      <ul className="grid gap-1">
        {SKILL_SOURCES.map((source) => {
          const count = skills.filter(
            (skill) => skill.source === source && skill.shadowed_by === null,
          ).length;
          const checked = chosen.includes(source);
          const id = `local-skills-${source}`;
          return (
            <li key={source} className="flex items-center gap-2 text-sm">
              <Checkbox
                id={id}
                checked={checked}
                disabled={toggle.isPending}
                onCheckedChange={(on) =>
                  toggle.mutate(
                    on === true
                      ? SKILL_SOURCES.filter((s) => s === source || chosen.includes(s))
                      : chosen.filter((s) => s !== source),
                  )
                }
              />
              <label htmlFor={id} className="flex min-w-0 flex-1 items-baseline justify-between">
                <span className="font-mono text-xs">{FOLDERS[source]}</span>
                <span className="text-muted-foreground text-xs">{t("count", { count })}</span>
              </label>
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <p className="text-muted-foreground mt-2 text-xs">{t("hidden", { count: hidden })}</p>
      )}
      <p className="text-muted-foreground mt-2 text-xs">{t(chosen.length > 0 ? "on" : "off")}</p>
    </div>
  );
}
