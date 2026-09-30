"use client";

import { useState } from "react";
import { Bot, RotateCcw, SendHorizontal, User } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Spinner, Textarea } from "@/components/ui";
import { useWorkflowRun, useWorkflowRuns } from "@/hooks";
import { isRunTerminal } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

interface Turn {
  prompt: string;
  runId: string;
}

/** A turn's answer: what the run's output says, how it failed, or that it is still running. */
function Answer({ runId }: { runId: string }) {
  const t = useTranslations("workflows");
  const { run } = useWorkflowRun(runId);
  if (run === null || !isRunTerminal(run.status)) {
    return (
      <span className="text-muted-foreground inline-flex items-center gap-2 text-sm">
        <Spinner className="size-3.5" />
        {t("chatPanelRunning")}
      </span>
    );
  }
  // The run's own failure, as the step recorded it - not a request that failed.
  const failed = run.error;
  if (failed !== null) {
    return <span className="text-destructive text-sm">{failed.message}</span>;
  }
  const text = run.output?.["text"];
  return typeof text === "string" && text !== "" ? (
    <span className="text-sm whitespace-pre-wrap">{text}</span>
  ) : (
    <span className="text-muted-foreground text-sm">{t("chatPanelNoAnswer")}</span>
  );
}

/**
 * **Open chat** for a draft that starts from a chat message: each message sent
 * here starts a test run of the draft with it, as the chat would, and the run's
 * answer shows under it - with the run opened on the canvas. The runs are test
 * runs started over the API, which carry no conversation to answer into, so
 * nothing said here reaches a real chat.
 */
export function ChatPanel({
  workflowId,
  blocked,
  onStarted,
}: {
  workflowId: string;
  /** Why a message cannot start a run now - problems to fix, a save in flight - or null. */
  blocked: string | null;
  onStarted: (runId: string) => void;
}) {
  const t = useTranslations("workflows");
  const watchRun = useWorkflowEditorStore((state) => state.watchRun);
  const { start } = useWorkflowRuns(workflowId);
  const [conversation, setConversation] = useState(() => crypto.randomUUID());
  const [turns, setTurns] = useState<Turn[]>([]);
  const [prompt, setPrompt] = useState("");

  const send = () => {
    const text = prompt.trim();
    if (text === "" || blocked !== null) return;
    start.mutate(
      {
        workflow_id: workflowId,
        mode: "test",
        input: { prompt: text, conversation_id: conversation, user_id: null },
      },
      {
        onSuccess: (run) => {
          setTurns((current) => [...current, { prompt: text, runId: run.id }]);
          setPrompt("");
          watchRun(run.id);
          onStarted(run.id);
        },
      },
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs">{t("chatPanelHint")}</p>
        <Button
          variant="ghost"
          size="sm"
          disabled={turns.length === 0}
          onClick={() => {
            setTurns([]);
            setConversation(crypto.randomUUID());
          }}
        >
          <RotateCcw className="size-3.5" />
          {t("chatPanelNew")}
        </Button>
      </div>
      <ol aria-label={t("chatPanelMessages")} className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {turns.length === 0 && (
          <li className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-xs">
            {t("chatPanelEmpty")}
          </li>
        )}
        {turns.map((turn) => (
          <li key={turn.runId} className="space-y-2">
            <p className="bg-muted ml-8 flex gap-2 rounded-lg px-3 py-2 text-sm">
              <User aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              <span className="whitespace-pre-wrap">{turn.prompt}</span>
            </p>
            <div className="mr-8 flex gap-2 rounded-lg border px-3 py-2">
              <Bot aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              <Answer runId={turn.runId} />
            </div>
          </li>
        ))}
      </ol>
      {blocked !== null && <p className="text-muted-foreground text-xs">{blocked}</p>}
      <div className="flex items-end gap-2">
        <Textarea
          aria-label={t("chatPanelMessage")}
          placeholder={t("chatPanelPlaceholder")}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          className="min-h-10 flex-1 resize-none"
        />
        <Button
          size="icon"
          aria-label={t("chatPanelSend")}
          disabled={prompt.trim() === "" || blocked !== null || start.isPending}
          onClick={send}
        >
          {start.isPending ? <Spinner className="size-4" /> : <SendHorizontal className="size-4" />}
        </Button>
      </div>
    </div>
  );
}
