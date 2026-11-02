"use client";

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
import { getLocalState, revokeWholeComputer, type LocalTarget } from "@/lib/desktop/commands";
import { getErrorMessage } from "@/lib/api-error";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { CodingHarness } from "@/types/chat";

/** A personal coding harness for this conversation, without changing the agent. */
export function LocalCodingControl() {
  const t = useTranslations("chat.controls.workOn.coding");
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
      harness: CodingHarness | null;
      target: LocalTarget | null;
      chooseFolder?: boolean;
    }) => {
      if (choice.harness === null) return { target: choice.target };
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
  const missingFolder =
    effective !== null &&
    (target === null || target.mode !== "full_access" || target.computer_grant !== undefined);
  return (
    <div className="pt-5" data-tour="chat-local-coding">
      <div className="mb-2 flex items-center gap-1">
        <p className="text-foreground/85 text-[13px] font-medium">{t("title")}</p>
        <ContextHelp>{t("help")}</ContextHelp>
      </div>
      <select
        aria-label={t("title")}
        value={chosen ?? "agent"}
        disabled={device === undefined || selection.isPending}
        className="border-foreground/10 bg-background h-9 w-full rounded-lg border px-3 text-xs"
        onChange={(event) => {
          const value = event.target.value;
          if (value === "agent" || value === "claude_code" || value === "codex")
            selection.mutate({ conversationId, harness: value === "agent" ? null : value, target });
        }}
      >
        <option value="agent">
          {published
            ? t("agentWithHarness", {
                agent: tHarness(published.harness === "codex" ? "codex" : "claudeCode"),
              })
            : t("agent")}
        </option>
        <option value="claude_code">{t("claudeCode")}</option>
        <option value="codex">{t("codex")}</option>
      </select>
      <p className="text-muted-foreground mt-2 text-xs">{t("description")}</p>
      {effective && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2 w-full"
          disabled={selection.isPending}
          onClick={() =>
            selection.mutate({ conversationId, harness: effective, target, chooseFolder: true })
          }
        >
          {target && !target.computer_grant
            ? t("changeFolder", { folder: target.folder })
            : t("pickFolder")}
        </Button>
      )}
      {missingFolder && (
        <p role="status" className="mt-2 text-xs">
          {t("folder")}
        </p>
      )}
      {effective && agents.data?.find((agent) => agent.id === effective)?.signed_in !== true && (
        <p role="status" className="text-muted-foreground mt-2 text-xs">
          {t("setup")}
        </p>
      )}
      {selection.error && (
        <p role="alert" className="text-destructive mt-2 text-xs">
          {getErrorMessage(selection.error, tErrors)}
        </p>
      )}
    </div>
  );
}
