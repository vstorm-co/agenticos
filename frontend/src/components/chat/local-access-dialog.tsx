"use client";

import { useMutation } from "@tanstack/react-query";
import { FolderOpen, Laptop } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDeviceLink, useDeviceStatus, useLocalFolders } from "@/hooks/use-desktop";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { allowWholeComputer, type LocalTarget } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import { useConversationStore } from "@/stores";
import { useLocalAccessStore, type LocalAccessAgent } from "@/stores/local-access-store";

/**
 * Where an agent that works on this computer may work, asked once for that agent.
 *
 * Opened when the running agent asks for the computer. The whole
 * computer is the agent's native consent in the app; a folder is a folder grant.
 * Either answer is remembered for the agent; Work on changes or revokes it later.
 */
export function LocalAccessDialog() {
  const asking = useLocalAccessStore((state) => state.asking);
  const answer = useLocalAccessStore((state) => state.answer);
  return (
    <Dialog open={asking !== null} onOpenChange={(open) => !open && answer(null)}>
      {asking && <LocalAccessChoice agent={asking} onAnswer={answer} />}
    </Dialog>
  );
}

function LocalAccessChoice({
  agent,
  onAnswer,
}: {
  agent: LocalAccessAgent;
  onAnswer: (target: LocalTarget | null) => void;
}) {
  const t = useTranslations("chat.localAccess");
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state, pick } = useLocalFolders();
  const modes = state.data?.modes ?? [];
  const folderMode = agent.coding
    ? modes.includes("full_access")
      ? "full_access"
      : null
    : modes.includes("workspace_write")
      ? "workspace_write"
      : modes.includes("read_only")
        ? "read_only"
        : null;
  const choose = useMutation({
    mutationFn: async (choice: "computer" | "folder"): Promise<LocalTarget | null> => {
      if (device?.linked !== true && !(await link.mutateAsync()).linked) return null;
      if (choice === "computer")
        return allowWholeComputer(useConversationStore.getState().currentConversationId, {
          id: agent.id,
          name: agent.name,
        });
      // A coding agent runs as the person, so its folder needs full access.
      if (folderMode === null) return null;
      const grant = await pick.mutateAsync(folderMode);
      return grant === null ? null : { folder: grant.path, mode: grant.mode };
    },
    onSuccess: (target) => {
      if (target !== null) onAnswer(target);
    },
    onError: (error) => {
      reportShellFailure("choosing where an agent works", error);
      toast.error(t("failed"));
    },
  });
  return (
    <DialogContent className={DIALOG_CONFIRM}>
      <DialogHeader>
        <DialogTitle>{t("title", { agent: agent.name })}</DialogTitle>
        <DialogDescription>{t("description", { agent: agent.name })}</DialogDescription>
      </DialogHeader>
      {agent.reason && <p className="text-sm whitespace-pre-wrap">{agent.reason}</p>}
      <div className="grid gap-2">
        <Button
          type="button"
          variant="outline"
          className="h-auto justify-start py-3 text-left"
          disabled={choose.isPending || device === undefined}
          onClick={() => choose.mutate("computer")}
        >
          <Laptop aria-hidden />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{t("computer")}</span>
            <span className="text-muted-foreground block text-xs font-normal whitespace-normal">
              {t("computerHint")}
            </span>
          </span>
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-auto justify-start py-3 text-left"
          disabled={choose.isPending || device === undefined || folderMode === null}
          onClick={() => choose.mutate("folder")}
        >
          <FolderOpen aria-hidden />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{t("folder")}</span>
            <span className="text-muted-foreground block text-xs font-normal whitespace-normal">
              {t("folderHint")}
            </span>
          </span>
        </Button>
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={() => onAnswer(null)}>
          {t("cancel")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
