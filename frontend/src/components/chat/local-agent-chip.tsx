"use client";

import { useTranslations } from "next-intl";

import { BrandIcon } from "@/components/icons/brand-icon";
import { useAgents } from "@/hooks/use-agents";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { cn } from "@/lib/utils";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";

/** The last part of a path, which is what a person recognises a folder by. */
function folderName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

/**
 * Which coding agent will work where, shown above the composer in the desktop
 * app when the chosen agent runs Claude Code or Codex on this computer (#2576).
 *
 * The agent starts in a folder the person granted *full access*, because it runs
 * as them; so the chip says the agent, the folder and what it may do - or, when
 * the chat is not set up for it, what is missing, before the person sends.
 */
export function LocalAgentChip() {
  const shell = useShell();
  return isDesktopShell(shell) ? <Chip /> : null;
}

function Chip() {
  const t = useTranslations("chat.localAgent");
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const target = useWorkOnStore((state) => state.targetFor(conversationId));
  const { agents } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const local = agents.find((agent) => agent.id === selectedAgentId)?.local_coding_agent;
  if (!local) return null;

  const agent = t(local.harness === "codex" ? "codex" : "claudeCode");
  const problem =
    target === null || target.computer_grant !== undefined
      ? "needsFolder"
      : target.mode !== "full_access"
        ? "needsFullAccess"
        : null;
  return (
    <p
      className={cn(
        "bg-foreground/[0.06] text-foreground/75 mb-2 inline-flex max-w-full items-center gap-1.5 rounded-md px-2 py-1 text-xs",
        problem && "bg-amber-500/15 text-amber-900 dark:text-amber-200",
      )}
      role={problem ? "status" : undefined}
    >
      <BrandIcon name={local.harness} className="size-3.5 shrink-0" />
      <span className={cn(!problem && "truncate")}>
        {problem
          ? t(problem, { agent })
          : t("ready", {
              agent,
              folder: folderName(target?.folder ?? ""),
              access: t(local.access === "edit" ? "edit" : "readOnly"),
            })}
      </span>
    </p>
  );
}
