"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { PublishDialog } from "@/components/agents/publish-dialog";
import { useAgentVersions } from "@/hooks/use-agents";
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import type { useChatAgentSettings } from "@/hooks/use-chat-agent-settings";

export function ChatAgentSettingsPublish({
  editor,
}: {
  editor: ReturnType<typeof useChatAgentSettings>;
}) {
  const t = useTranslations("chat.agentSettings");
  const agentId = editor.agent!.id;
  const { versions, isLoading: versionsLoading, error: versionsError } = useAgentVersions(agentId);
  const {
    environments,
    isLoading: environmentsLoading,
    error: environmentsError,
  } = useAgentEnvironments(agentId);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const nextVersion = versions.reduce((max, entry) => Math.max(max, entry.version), 0) + 1;
  const contextFailed = Boolean(versionsError || environmentsError);
  if (editor.remote.held && open) setOpen(false);
  const prepare = async () => {
    if (editor.blocked || checking) return;
    setChecking(true);
    setProblems([]);
    try {
      if (editor.dirty && !(await editor.save())) return;
      if (!active.current) return;
      const result = await editor.validate();
      if (!active.current) return;
      setProblems(result.problems);
      if (result.problems.length === 0) setOpen(true);
    } finally {
      setChecking(false);
    }
  };
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void prepare()}
        disabled={
          editor.blocked ||
          checking ||
          editor.publish.isPending ||
          versionsLoading ||
          environmentsLoading ||
          contextFailed
        }
      >
        {checking ? t("checking") : t("publish")}
      </Button>
      {contextFailed && (
        <p role="alert" className="text-destructive basis-full text-xs">
          {t("publishContextFailed")}
        </p>
      )}
      {problems.length > 0 && (
        <ul role="alert" className="text-destructive basis-full space-y-1 text-xs">
          {problems.map((problem, index) => (
            <li key={index}>{problem}</li>
          ))}
        </ul>
      )}
      <PublishDialog
        open={open && !editor.remote.held}
        onOpenChange={setOpen}
        version={nextVersion}
        environments={environments}
        publishing={editor.publish.isPending}
        onConfirm={async () => {
          if (editor.remote.held || editor.dirty) {
            setOpen(false);
            return;
          }
          try {
            await editor.publish.mutateAsync(null);
            setOpen(false);
          } catch {
            // The existing mutation reports the refusal and leaves confirmation retryable.
          }
        }}
      />
    </>
  );
}
