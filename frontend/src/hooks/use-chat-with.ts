"use client";

import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore, useComposerIntentStore } from "@/stores";
import { useConversations } from "@/hooks/use-conversations";

/**
 * Explicit new-chat links from the desktop shell and pinned agents. Plain /chat
 * resumes the open thread. Each ?new= request starts fresh through the same
 * action as the console's button, including when this page is already mounted.
 *
 * A ?prompt= link hands its words to the composer instead of sending them: the
 * reader finishes the sentence and sends it. It rides the same hand-off the
 * phone app's share uses, so the composer takes it once, after whatever is
 * already typed - and the address is cleaned, so a refresh does not write it
 * again over an edited draft.
 */
export function useChatWith(): void {
  const params = useSearchParams();
  const agentId = params.get("with");
  const request = params.get("new");
  const prompt = params.get("prompt");
  const select = useAgentSelectionStore((state) => state.select);
  const share = useComposerIntentStore((state) => state.share);
  const { startNewChat } = useConversations();
  const consumed = useRef<string | null>(null);
  const consumedPrompt = useRef<string | null>(null);

  useEffect(() => {
    const key = request || agentId;
    if (!key) {
      consumed.current = null;
    } else if (consumed.current !== key) {
      consumed.current = key;
      void startNewChat();
      if (agentId) select(agentId);
      if (request) setUrlParam("new", null);
      if (agentId) setUrlParam("with", null);
    }
    if (!prompt) {
      consumedPrompt.current = null;
      return;
    }
    if (consumedPrompt.current === prompt) return;
    consumedPrompt.current = prompt;
    share({ id: Date.now(), files: [], text: prompt });
    setUrlParam("prompt", null);
  }, [request, agentId, prompt, select, share, startNewChat]);
}
