"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useAssistant } from "@/hooks/use-assistant";
import { useArchitectAskStore } from "@/stores/architect-ask-store";

/** Open the Architect without submitting a prompt or creating an agent. */
export function DescribeWithArchitect({ onAsked }: { onAsked: () => void }) {
  const t = useTranslations("authoring.describe");
  const { assistant } = useAssistant();
  const open = useArchitectAskStore((state) => state.open);
  if (!assistant?.can_use || assistant.status !== "ready" || assistant.agent_id === null) {
    return null;
  }

  return (
    <Button
      variant="ghost"
      onClick={() => {
        onAsked();
        open();
      }}
    >
      <Sparkles aria-hidden />
      {t("open", { name: assistant.name })}
    </Button>
  );
}
