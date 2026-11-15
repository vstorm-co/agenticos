"use client";

import { cn } from "@/lib/utils";
import type { PublishedModel } from "@/types/agents";
import { ChatModelSelector } from "./chat-model-selector";

export function ChatModelHeader({
  name,
  agentModel,
  readOnly,
  isProcessing,
  home,
  onChange,
}: {
  name: string;
  agentModel: PublishedModel | null;
  readOnly: boolean;
  isProcessing: boolean;
  home: boolean;
  onChange: (profileId: string | null) => void;
}) {
  return (
    <header
      data-chat-model-header
      className={cn(
        "bg-background/95 z-20 flex min-h-14 shrink-0 items-center justify-between gap-3 border-b px-4 py-2 max-lg:pt-16 sm:px-6",
        home && "absolute inset-x-0 top-0",
      )}
    >
      <span className="min-w-0 truncate text-sm font-medium">{name}</span>
      <ChatModelSelector
        agentModel={agentModel}
        readOnly={readOnly}
        isProcessing={isProcessing}
        onChange={onChange}
      />
    </header>
  );
}
