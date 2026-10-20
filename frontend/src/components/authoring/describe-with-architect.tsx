"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Label, Textarea } from "@/components/ui";
import { useAssistant } from "@/hooks/use-assistant";
import { useAiAssistance } from "@/hooks/use-organizations";
import { useArchitectAskStore } from "@/stores/architect-ask-store";

/**
 * Describe the agent instead of filling the form, and let the Architect draft it.
 *
 * The Architect already drafts agents and asks before it creates one, so this
 * hands it the description rather than building a second way to do the same.
 * Absent when the Architect is off or AI assistance is.
 */
export function DescribeWithArchitect({ onAsked }: { onAsked: () => void }) {
  const t = useTranslations("authoring.describe");
  const { assistant } = useAssistant();
  const { enabled } = useAiAssistance();
  const ask = useArchitectAskStore((state) => state.ask);
  const [text, setText] = useState("");
  if (!assistant?.can_use || assistant.agent_id === null || enabled !== true) return null;

  return (
    <div className="bg-muted/40 space-y-2 rounded-md border p-3">
      <Label htmlFor="describe-agent" className="flex items-center gap-1.5">
        <Sparkles className="text-primary h-4 w-4" aria-hidden />
        {t("label", { name: assistant.name })}
      </Label>
      <Textarea
        id="describe-agent"
        rows={3}
        value={text}
        placeholder={t("placeholder")}
        onChange={(event) => setText(event.target.value)}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={text.trim() === ""}
        onClick={() => {
          ask(t("prompt", { description: text.trim() }));
          onAsked();
        }}
      >
        {t("send")}
      </Button>
    </div>
  );
}
