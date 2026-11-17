"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { PublishedModel } from "@/types/agents";
import { ChatModelSelector } from "./chat-model-selector";

export function ChatModelHeader({
  name,
  agentModel,
  readOnly,
  isProcessing,
  canEditAgent,
  home,
  onChange,
  actions,
}: {
  name: string;
  agentModel: PublishedModel | null;
  readOnly: boolean;
  isProcessing: boolean;
  canEditAgent: boolean;
  home: boolean;
  onChange: (profileId: string | null) => void;
  actions?: ReactNode;
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
      <div className="flex shrink-0 items-center gap-1">
        {actions}
        <ChatModelSelector
          key={isProcessing ? "processing" : "idle"}
          agentModel={agentModel}
          readOnly={readOnly}
          isProcessing={isProcessing}
          canEditAgent={canEditAgent}
          onChange={onChange}
        />
      </div>
    </header>
  );
}
