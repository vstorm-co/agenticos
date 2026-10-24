"use client";

import { ChatContainer, ConversationSidebar } from "@/components/chat";
import { PhoneChatBar } from "@/components/chat/phone-chat-bar";
import { useMcpOAuthOutcome } from "@/hooks";
import { useChatWith } from "@/hooks/use-chat-with";
import { SAFE_AREA_CLEARANCE } from "@/lib/page-clearance";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  // A consent started from the chat comes back here, and the outcome is in the
  // query string exactly as it is on the servers page.
  useMcpOAuthOutcome();
  // Desktop New Chat and pinned-agent links explicitly start a fresh conversation.
  useChatWith();
  // The ?id= query param is read by useConversations.fetchConversations on mount;
  // it sets currentConversationId AND loads messages atomically. Pre-setting the
  // id here would short-circuit that loader and leave the chat empty on refresh.
  return (
    <div className={cn("-mx-3 -mt-4 flex min-h-0 flex-1 sm:-mx-6 sm:-mt-8", SAFE_AREA_CLEARANCE)}>
      <ConversationSidebar />
      {/* Room at the top of the transcript for
          the buttons floating over it on a phone. */}
      <div className="relative min-w-0 flex-1 max-md:[&_[data-transcript]]:pt-16">
        <PhoneChatBar />
        <ChatContainer />
      </div>
    </div>
  );
}
