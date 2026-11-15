"use client";

import { useSearchParams } from "next/navigation";

import { ChatContainer, ConversationSidebar } from "@/components/chat";
import { PhoneChatBar } from "@/components/chat/phone-chat-bar";
import { useMcpOAuthOutcome } from "@/hooks";
import { useChatWith } from "@/hooks/use-chat-with";
import { SAFE_AREA_CLEARANCE } from "@/lib/page-clearance";
import { StartExample } from "@/components/onboarding/start-example";
import { startGoal } from "@/lib/onboarding-api";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const example = startGoal(useSearchParams().get("example"));
  const requestedConversationId = useSearchParams().get("id");
  // A consent started from the chat comes back here, and the outcome is in the
  // query string exactly as it is on the servers page.
  useMcpOAuthOutcome();
  // Desktop New Chat and pinned-agent links explicitly start a fresh conversation.
  useChatWith();
  // The ?id= query param is read by useConversations.fetchConversations on mount;
  // it sets currentConversationId AND loads messages atomically. Pre-setting the
  // id here would short-circuit that loader and leave the chat empty on refresh.
  return (
    <div className={cn("flex min-h-0 flex-1", SAFE_AREA_CLEARANCE)}>
      <ConversationSidebar />
      {/* Room at the top of the transcript for
          the buttons floating over it on a phone. */}
      <div className="relative min-w-0 flex-1 max-md:[&_[data-chat-scroller]]:scroll-pt-20 max-md:[&_[data-transcript]]:pt-20">
        <PhoneChatBar />
        <ChatContainer
          requestedConversationId={requestedConversationId}
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
