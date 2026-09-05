"use client";

import { ChatContainer, ConversationSidebar } from "@/components/chat";
import { useMcpOAuthOutcome } from "@/hooks";

export default function ChatPage() {
  // A consent started from the chat comes back here, and the outcome is in the
  // query string exactly as it is on the servers page.
  useMcpOAuthOutcome();
  // The ?id= query param is read by useConversations.fetchConversations on mount;
  // it sets currentConversationId AND loads messages atomically. Pre-setting the
  // id here would short-circuit that loader and leave the chat empty on refresh.
  return (
    <div className="-mx-3 -mt-4 flex min-h-0 flex-1 sm:-mx-6 sm:-mt-8">
      <ConversationSidebar />
      <div className="min-w-0 flex-1">
        <ChatContainer />
      </div>
    </div>
  );
}
