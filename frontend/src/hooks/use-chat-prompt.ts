"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { IncomingFiles } from "@/components/chat/chat-input";
import { setUrlParam } from "@/lib/utils";

/**
 * A stable id for a prompt hand-off, from the words themselves: the composer's
 * once-per-hand-off guard keys on it, and a pure derivation keeps the hook
 * render-clean where `Date.now()` would not be.
 */
function promptId(prompt: string): number {
  let hash = 5381;
  for (let i = 0; i < prompt.length; i += 1) {
    hash = ((hash << 5) + hash + prompt.charCodeAt(i)) | 0;
  }
  return hash;
}

/**
 * A chat address carrying a prompt to start from — `/chat?new=1&prompt=...`,
 * as the workflows list's "Describe a workflow" sends.
 *
 * The text lands in the composer through ChatContainer's `incomingFiles`, the
 * same hand-off the phone app's shared content takes: written once, after
 * whatever is already typed, and never sent on the reader's behalf. The
 * parameter is taken off the address once read, so a refresh does not seed
 * the same words a second time.
 */
export function useChatPrompt(): IncomingFiles | null {
  const params = useSearchParams();
  const prompt = params.get("prompt");
  const [incoming, setIncoming] = useState<IncomingFiles | null>(null);
  const [seen, setSeen] = useState<string | null>(null);
  if (prompt !== seen) {
    setSeen(prompt);
    setIncoming(
      prompt === null || prompt === "" ? null : { id: promptId(prompt), files: [], text: prompt },
    );
  }
  useEffect(() => {
    if (prompt) setUrlParam("prompt", null);
  }, [prompt]);
  return incoming;
}
