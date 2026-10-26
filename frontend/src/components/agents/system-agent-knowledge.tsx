"use client";

import { useTranslations } from "next-intl";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Switch,
} from "@/components/ui";
import { KNOWLEDGE_ID } from "@/lib/agent-spec";
import { SYSTEM_AGENT_MAX_STEPS, SYSTEM_AGENT_SEARCH_STEPS } from "@/lib/system-agents";
import type { CapabilityBindingSpec, SystemAgentKind } from "@/types/agents";

interface SystemAgentKnowledgeProps {
  kind: SystemAgentKind;
  capabilities: CapabilityBindingSpec[];
  /** `spec.max_steps`; unset runs a search in `SYSTEM_AGENT_SEARCH_STEPS`. */
  maxSteps: number | null | undefined;
  onToggle: () => void;
  onMaxSteps: (maxSteps: number | null) => void;
  disabled: boolean;
}

/**
 * Whether a system agent searches a knowledge base while it works, and in how
 * many steps.
 *
 * There is no collection to pick: the platform hands each run the knowledge
 * bases it is about - the graded agent's, the gap's, the ones a generation
 * drafts from - which is why the sentence under the title changes with the kind.
 */
export function SystemAgentKnowledge({
  kind,
  capabilities,
  maxSteps,
  onToggle,
  onMaxSteps,
  disabled,
}: SystemAgentKnowledgeProps) {
  const t = useTranslations("agents");
  const on = capabilities.some((binding) => binding.id === KNOWLEDGE_ID && binding.enabled);

  return (
    <Card>
      <CardHeader data-tour="agent-system-knowledge">
        <CardTitle>{t("systemAgentKnowledge")}</CardTitle>
        <CardDescription>{t("systemAgentKnowledgeHelp", { kind })}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="system-agent-knowledge">{t("systemAgentKnowledgeSwitch")}</Label>
          <Switch
            id="system-agent-knowledge"
            checked={on}
            disabled={disabled}
            onCheckedChange={onToggle}
          />
        </div>
        {on && (
          <div className="space-y-2">
            <Label htmlFor="system-agent-max-steps">{t("systemAgentMaxSteps")}</Label>
            <Input
              id="system-agent-max-steps"
              type="number"
              step="1"
              min="1"
              max={SYSTEM_AGENT_MAX_STEPS}
              value={maxSteps ?? ""}
              disabled={disabled}
              placeholder={String(SYSTEM_AGENT_SEARCH_STEPS)}
              aria-describedby="system-agent-max-steps-hint"
              className="max-w-32"
              onChange={(event) =>
                onMaxSteps(event.target.value ? Number(event.target.value) : null)
              }
            />
            <p id="system-agent-max-steps-hint" className="text-muted-foreground text-xs">
              {t("systemAgentMaxStepsHint", {
                max: SYSTEM_AGENT_MAX_STEPS,
                fallback: SYSTEM_AGENT_SEARCH_STEPS,
              })}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
