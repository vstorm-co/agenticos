"use client";

import { useSmoothText } from "@/hooks/use-smooth-text";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { useInChatScope } from "@/stores/chat-scope-context";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";
import { ModelSetupCard } from "./model-setup-card";

/** A local setup response reveals like a normal answer, without pretending to run AI. */
export function ModelSetupReply({ text, agentId }: { text: string; agentId?: string }) {
  const compact = useInChatScope();
  const reduced = useReducedMotion();
  const visible = useSmoothText(text, false, true);
  const typing = !reduced && visible.length < text.length;
  return (
    <>
      <div
        className={cn(
          "prose-sm max-w-none leading-relaxed",
          compact ? "text-[13.5px]" : "text-[15px]",
          typing && "stream-in",
        )}
      >
        <MarkdownContent content={reduced ? text : visible} streaming={typing} />
        {typing && (
          <span
            aria-hidden
            className="stream-cursor ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-current"
          />
        )}
      </div>
      {!typing && <ModelSetupCard agentId={agentId} interactive />}
    </>
  );
}
