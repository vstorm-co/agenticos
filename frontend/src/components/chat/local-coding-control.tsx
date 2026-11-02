"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ContextHelp } from "@/components/ui/context-help";
import { useDeviceLink, useDeviceStatus, useLocalAgents } from "@/hooks/use-desktop";
import { getErrorMessage } from "@/lib/api-error";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { CodingHarness } from "@/types/chat";

/** A personal coding harness for this conversation, without changing the agent. */
export function LocalCodingControl() {
  const t = useTranslations("chat.controls.workOn.coding");
  const tErrors = useTranslations("errors");
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const chosen = useWorkOnStore((state) => state.codingFor(conversationId));
  const target = useWorkOnStore((state) => state.targetFor(conversationId));
  const setCoding = useWorkOnStore((state) => state.setCoding);
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state: agents } = useLocalAgents();
  const selection = useMutation({
    mutationFn: async (choice: { conversationId: string | null; harness: CodingHarness | null }) =>
      choice.harness === null || device?.linked === true || (await link.mutateAsync()).linked,
    onSuccess: (linked, choice) => {
      if (linked) setCoding(choice.conversationId, choice.harness);
    },
  });
  const missingFolder =
    chosen !== null &&
    (target === null || target.mode !== "full_access" || target.computer_grant !== undefined);
  return (
    <div className="border-foreground/10 mt-4 border-t pt-4" data-tour="chat-local-coding">
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
            selection.mutate({ conversationId, harness: value === "agent" ? null : value });
        }}
      >
        <option value="agent">{t("agent")}</option>
        <option value="claude_code">{t("claudeCode")}</option>
        <option value="codex">{t("codex")}</option>
      </select>
      <p className="text-muted-foreground mt-2 text-xs">{t("description")}</p>
      {missingFolder && (
        <p role="status" className="mt-2 text-xs">
          {t("folder")}
        </p>
      )}
      {chosen && agents.data?.find((agent) => agent.id === chosen)?.signed_in !== true && (
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
