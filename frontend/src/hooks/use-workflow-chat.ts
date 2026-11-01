"use client";

import { useCallback, useEffect, useRef } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { clientId } from "@/lib/ids";
import { isRunTerminal, type WorkflowRunRead } from "@/lib/workflows/types";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { Conversation, WorkflowRunPart } from "@/types";

interface UseWorkflowChatOptions {
  /** Open a conversation for a first message sent in a new chat. */
  createConversation: (title?: string) => Promise<Conversation | null>;
  /** Told when a first message opened a conversation, so the list shows it. */
  onConversationCreated?: () => void;
}

type Frame =
  | { type: "run"; run: WorkflowRunRead }
  | { type: "event" }
  | { type: "error"; code: string; message: string };

/**
 * Hand a chat message to a workflow and show its run in the thread.
 *
 * Each message opens its own `/ws/workflow-runs` socket and sends a `start`
 * frame naming the conversation: the server writes the message there, starts
 * the run as the signed-in member, and writes the answer back when the run
 * ends. The card this adds follows the run until then, and the composer stays
 * free meanwhile: a workflow can take minutes, and nothing here waits on it -
 * the agent's Stop could not stop it anyway. Closing the page loses
 * nothing - the answer is written server-side whether or not anyone is
 * watching, and reopening the conversation reads it back.
 */
export function useWorkflowChat({
  createConversation,
  onConversationCreated,
}: UseWorkflowChatOptions) {
  const { wsUrl } = usePublicConfig();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const sockets = useRef(new Set<WebSocket>());

  useEffect(() => {
    const open = sockets.current;
    return () => {
      for (const socket of open) socket.close();
      open.clear();
    };
  }, []);

  const send = useCallback(
    async (workflow: { id: string; name: string }, text: string) => {
      let conversationId = useConversationStore.getState().currentConversationId;
      if (conversationId === null) {
        const created = await createConversation(text.slice(0, 80));
        if (created === null) return;
        conversationId = created.id;
        useConversationStore.getState().setCurrentConversationId(conversationId);
        onConversationCreated?.();
      }

      const { addMessage, updateMessage } = useChatStore.getState();
      addMessage({
        id: clientId(),
        role: "user",
        content: text,
        timestamp: new Date(),
        conversationId,
      });
      const answerId = clientId();
      const partId = `${answerId}-workflow_run`;
      const card: WorkflowRunPart = {
        workflowId: workflow.id,
        workflowName: workflow.name,
        runId: null,
        status: "queued",
        error: null,
      };
      addMessage({
        id: answerId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isStreaming: true,
        conversationId,
        parts: [{ id: partId, type: "workflow_run", workflowRun: card }],
      });
      // The card, then the run's words once it has them - the order the stored
      // turn replays in.
      const show = (change: Partial<WorkflowRunPart>, answer?: string, done = false) =>
        updateMessage(answerId, (message) => {
          const current = message.parts?.[0]?.workflowRun ?? card;
          const words = answer ?? message.content;
          return {
            ...message,
            content: words,
            isStreaming: !done,
            parts: [
              { id: partId, type: "workflow_run", workflowRun: { ...current, ...change } },
              ...(words ? [{ id: `${answerId}-text`, type: "text" as const, content: words }] : []),
            ],
          };
        });

      const token = useAuthStore.getState().accessToken;
      const base = `${wsUrl}/api/v1/ws/workflow-runs`;
      const url = activeOrgId ? `${base}?organization_id=${encodeURIComponent(activeOrgId)}` : base;
      const socket = new WebSocket(url, token ? [`access_token.${token}`, "workflow"] : undefined);
      sockets.current.add(socket);
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        sockets.current.delete(socket);
        socket.close();
      };

      socket.onopen = () =>
        socket.send(
          JSON.stringify({
            type: "start",
            workflow_id: workflow.id,
            conversation_id: conversationId,
            message: text,
          }),
        );
      socket.onmessage = (event: MessageEvent<string>) => {
        const frame = JSON.parse(event.data) as Frame;
        if (frame.type === "error") {
          show({ status: "failed", error: frame.message }, undefined, true);
          finish();
          return;
        }
        if (frame.type !== "run") return;
        const { run } = frame;
        if (!isRunTerminal(run.status)) {
          show({ runId: run.id, status: run.status });
          return;
        }
        const answer = typeof run.output?.text === "string" ? run.output.text : "";
        show(
          { runId: run.id, status: run.status, error: run.error?.message ?? null },
          answer,
          true,
        );
        finish();
      };
      // A socket that went away before the run ended leaves the card where it
      // was; the answer still lands in the conversation, and a reload reads it.
      socket.onclose = () => {
        if (!finished) show({}, undefined, true);
        finish();
      };
    },
    [wsUrl, activeOrgId, createConversation, onConversationCreated],
  );

  return { send };
}
