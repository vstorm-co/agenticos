"use client";

import { Check, SlidersHorizontal } from "lucide-react";
import { BrandIcon } from "@/components/icons/brand-icon";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ContextHelp } from "@/components/ui/context-help";
import { Button } from "@/components/ui/button";
import {
  useDeviceLink,
  useDeviceStatus,
  useLocalAgents,
  useLocalFolders,
} from "@/hooks/use-desktop";
import {
  getLocalState,
  revokeWholeComputer,
  type LocalAgent,
  type LocalTarget,
} from "@/lib/desktop/commands";
import { getErrorMessage } from "@/lib/api-error";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { useWorkOnStore } from "@/stores/work-on-store";
import { LocalCodingSettings } from "./local-coding-settings";

/** A personal coding harness for this conversation, without changing the agent. */
export function LocalCodingControl() {
  const t = useTranslations("chat.controls.workOn.coding");
  const tWork = useTranslations("chat.controls.workOn");
  const tHarness = useTranslations("chat.localAgent");
  const tErrors = useTranslations("errors");
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const chosen = useWorkOnStore((state) => state.codingFor(conversationId));
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents: publishedAgents } = useAgents();
  const published = publishedAgents.find(
    (agent) => agent.id === selectedAgentId,
  )?.local_coding_agent;
  const effective = chosen ?? published?.harness ?? null;
  const target = useWorkOnStore((state) => state.targetFor(conversationId));
  const setCoding = useWorkOnStore((state) => state.setCoding);
  const setTarget = useWorkOnStore((state) => state.set);
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state: agents } = useLocalAgents();
  const { pick } = useLocalFolders();
  const selection = useMutation({
    mutationFn: async (choice: {
      conversationId: string | null;
      harness: LocalAgent["id"] | null;
      target: LocalTarget | null;
      chooseFolder?: boolean;
    }) => {
      if (choice.harness === null) return { target: choice.target };
      // Whole-computer consent already covers a coding agent, in the home folder.
      if (choice.target?.computer_grant && !choice.chooseFolder) return { target: choice.target };
      if (device?.linked !== true && !(await link.mutateAsync()).linked) return null;
      const state = await getLocalState();
      const existing =
        !choice.chooseFolder && !choice.target?.computer_grant
          ? state.grants.find(
              (grant) => grant.path === choice.target?.folder && grant.mode === "full_access",
            )
          : undefined;
      const grant = existing ?? (await pick.mutateAsync("full_access"));
      if (!grant) return null;
      if (choice.target?.computer_grant) await revokeWholeComputer(choice.target.computer_grant);
      return {
        target: {
          ...choice.target,
          folder: grant.path,
          mode: grant.mode,
          computer_grant: undefined,
        },
      };
    },
    onSuccess: (prepared, choice) => {
      if (prepared) {
        setTarget(choice.conversationId, prepared.target);
        setCoding(choice.conversationId, choice.harness);
      }
    },
  });
  const missingFolder = effective !== null && (target === null || target.mode !== "full_access");
  return (
    <div
      className="border-foreground/10 bg-foreground/[0.02] rounded-xl border p-3"
      data-tour="chat-local-coding"
    >
      <div className="mb-2 flex items-center gap-1">
        <p className="text-foreground/85 text-[13px] font-medium">{t("title")}</p>
        <ContextHelp>{t("help")}</ContextHelp>
      </div>
      <div role="radiogroup" aria-label={t("title")} className="grid grid-cols-3 gap-1.5">
        {(["agent", "claude_code", "codex"] as const).map((value) => {
          const active = (chosen ?? "agent") === value;
          const label =
            value === "agent"
              ? published
                ? t("agentWithHarness", {
                    agent: tHarness(published.harness === "codex" ? "codex" : "claudeCode"),
                  })
                : t("agent")
              : tHarness(value === "codex" ? "codex" : "claudeCode");
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-label={label}
              title={value === "agent" ? undefined : t(value === "codex" ? "codex" : "claudeCode")}
              aria-checked={active}
              disabled={device === undefined || selection.isPending}
              onClick={() =>
                selection.mutate({
                  conversationId,
                  harness: value === "agent" ? null : value,
                  target,
                })
              }
              className={cn(
                "relative flex min-h-14 flex-col items-center justify-center gap-2 rounded-lg border px-1 py-2 text-[11px] font-medium transition-colors disabled:opacity-50",
                active
                  ? "border-foreground/30 bg-background shadow-sm"
                  : "text-muted-foreground hover:bg-foreground/[0.04] border-transparent",
              )}
            >
              {value === "agent" ? (
                <SlidersHorizontal className="size-4" aria-hidden />
              ) : (
                <BrandIcon name={value === "codex" ? "codex" : "claude_code"} className="size-4" />
              )}
              <span>{value === "agent" ? tWork("agentBrowser") : label}</span>
              {active && <Check className="absolute top-1.5 right-1.5 size-2.5" aria-hidden />}
            </button>
          );
        })}
      </div>
      {effective === null && (
        <p className="text-muted-foreground mt-2 text-xs leading-relaxed">{t("description")}</p>
      )}
      {effective && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3 w-full justify-start overflow-hidden text-ellipsis"
          disabled={selection.isPending}
          onClick={() =>
            selection.mutate({ conversationId, harness: effective, target, chooseFolder: true })
          }
        >
          <span className="truncate">
            {target && !target.computer_grant
              ? t("changeFolder", { folder: target.folder })
              : t("pickFolder")}
          </span>
        </Button>
      )}
      {missingFolder && (
        <p role="status" className="mt-2 text-xs">
          {t("folder")}
        </p>
      )}
      {effective && agents.data?.find((agent) => agent.id === effective)?.signed_in !== true && (
        <p role="status" className="text-muted-foreground mt-2 text-xs">
          <Link href="/settings/desktop" className="underline underline-offset-2">
            {t("setup")}
          </Link>
        </p>
      )}
      {selection.error && (
        <p role="alert" className="text-destructive mt-2 text-xs">
          {getErrorMessage(selection.error, tErrors)}
        </p>
      )}
      {effective !== null && !missingFolder && <LocalCodingSettings harness={effective} />}
    </div>
  );
}
