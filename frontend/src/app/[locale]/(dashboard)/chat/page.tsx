"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { ChatContainer, ConversationSidebar } from "@/components/chat";
import { PhoneChatBar } from "@/components/chat/phone-chat-bar";
import { useMcpOAuthOutcome } from "@/hooks";
import { useChatWith } from "@/hooks/use-chat-with";
import { SAFE_AREA_CLEARANCE } from "@/lib/page-clearance";
import { StartExample } from "@/components/onboarding/start-example";
import { startGoal } from "@/lib/onboarding-api";
import { cn } from "@/lib/utils";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useConversationStore } from "@/stores";

export default function ChatPage() {
  const params = useSearchParams();
  const example = startGoal(params.get("example"));
  const requestedConversationId = params.get("id");
  const requestedThreadRootId = params.get("thread");
  const router = useRouter();
  const pathname = usePathname();
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (requestedThreadRootId !== null) return;
    trigger.current?.focus();
    trigger.current = null;
  }, [requestedThreadRootId]);
  const changeThread = (root: string | null) => {
    const next = new URLSearchParams(params.toString());
    const id = useConversationStore.getState().currentConversationId;
    if (id !== null) next.set("id", id);
    if (root === null) next.delete("thread");
    else next.set("thread", root);
    router.push(`${pathname}?${next}`, { scroll: false });
  };
  // A consent started from the chat comes back here, and the outcome is in the
  // query string exactly as it is on the servers page.
  useMcpOAuthOutcome();
  // Desktop New Chat and pinned-agent links explicitly start a fresh conversation.
  useChatWith();
  // The ?id= query param is read by useConversations.fetchConversations on mount;
  // it sets currentConversationId AND loads messages atomically. Pre-setting the
  // id here would short-circuit that loader and leave the chat empty on refresh.
  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 overflow-hidden", SAFE_AREA_CLEARANCE)}>
      <ConversationSidebar />
      {/* Room at the top of the transcript for
          the buttons floating over it on a phone. */}
      <div className="relative min-h-0 min-w-0 flex-1 max-lg:[&_[data-chat-model-header]~[data-chat-scroller]_[data-transcript]]:pt-4 max-lg:[&_[data-chat-scroller]]:scroll-pt-20 max-lg:[&_[data-transcript]]:pt-20">
        <PhoneChatBar />
        <ChatContainer
          requestedConversationId={requestedConversationId}
          requestedThreadRootId={requestedThreadRootId}
          onOpenThread={(root) => {
            const opener = document.activeElement;
            // A notice inside a thread disappears when its root changes. Keep
            // the main-room opener so closing the final panel can restore focus.
            if (
              opener instanceof HTMLElement &&
              opener.closest('[data-tour="chat-room-thread-panel"]') === null
            )
              trigger.current = opener;
            changeThread(root);
          }}
          onCloseThread={() => {
            changeThread(null);
          }}
          emptyState={
            example
              ? (onPick) => <StartExample key={example} goal={example} onRun={onPick} />
              : undefined
          }
        />
      </div>
    </div>
  );
}
