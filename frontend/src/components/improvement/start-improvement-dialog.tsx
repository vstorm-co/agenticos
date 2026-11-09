"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useOrgStore } from "@/stores/org-store";
import type { Agent } from "@/types/agents";
import { StartSession } from "./start-session";

/** Configure a new session over the agent; the running session keeps its own workspace. */
export function StartImprovementDialog({
  agent,
  allowed,
  onClose,
}: {
  agent: Pick<Agent, "id" | "name" | "slug" | "has_avatar" | "avatar_color">;
  allowed: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("improvement");
  const tc = useTranslations("common");
  const title = useRef<HTMLHeadingElement>(null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent
        className={cn(DIALOG_WIDE, DIALOG_COLUMN)}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          title.current?.focus();
        }}
      >
        <DialogHeader>
          <div className="flex items-center gap-3 pr-6">
            <AgentAvatar
              agentId={agent.id}
              slug={agent.slug}
              hasAvatar={agent.has_avatar}
              colorSlot={agent.avatar_color}
              size="md"
            />
            <DialogTitle ref={title} tabIndex={-1} className="min-w-0 break-words outline-none">
              {t("title", { name: agent.name })}
            </DialogTitle>
          </div>
          <DialogDescription>{t("startDescription")}</DialogDescription>
        </DialogHeader>
        {allowed ? (
          <StartSession key={`${orgId}:${agent.id}`} agentId={agent.id} onClose={onClose} />
        ) : (
          <>
            <p role="alert" className="text-sm">
              {t("permission")}
            </p>
            <DialogFooter className="border-t">
              <Button variant="outline" onClick={onClose}>
                {tc("cancel")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
