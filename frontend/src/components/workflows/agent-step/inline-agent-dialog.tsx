"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { CapabilityWorkbench } from "@/components/agents/capability-workbench";
import { McpBindingsEditor } from "@/components/agents/mcp-bindings-editor";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { useCapabilityCatalog, useKnowledgeBases, useModelProviders } from "@/hooks";
import { useInlineAgentResources } from "@/hooks/use-inline-agent-resources";
import { ErrorState, LoadingState } from "@/components/states";
import { withCapability, withContextFiles, withSkills } from "@/lib/agent-spec";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

const toggled = (list: string[], value: string) =>
  list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

/** The capabilities an agent configured in a workflow step is not offered. */
const NOT_IN_A_STEP: ReadonlySet<string> = new Set(["subagents", "workflows"]);

/**
 * An agent configured inside a workflow step, edited where the Builder would
 * edit it - the same model picker, capability workbench and MCP editor - and
 * handed back whole when saved, so the step's config changes once rather than
 * on every keystroke.
 *
 * What it does not offer is what makes no sense for an agent that only ever runs
 * as a step: delegation and starting workflows, a monthly budget (the step has
 * its own ceiling), and the surfaces an agent is published to.
 */
export function InlineAgentDialog({
  open,
  spec,
  onOpenChange,
  onSave,
}: {
  open: boolean;
  spec: AgentSpec;
  onOpenChange: (open: boolean) => void;
  onSave: (spec: AgentSpec) => void;
}) {
  const t = useTranslations("workflows");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_CANVAS, DIALOG_FILL)}>
        <DialogHeader>
          <DialogTitle>{t("inlineAgentTitle")}</DialogTitle>
          <DialogDescription>{t("inlineAgentDescription")}</DialogDescription>
        </DialogHeader>
        {/* Keyed on opening, so each opening edits the step's current spec. */}
        {open && (
          <InlineAgentForm initial={spec} onCancel={() => onOpenChange(false)} onSave={onSave} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function InlineAgentForm({
  initial,
  onCancel,
  onSave,
}: {
  initial: AgentSpec;
  onCancel: () => void;
  onSave: (spec: AgentSpec) => void;
}) {
  const t = useTranslations("workflows");
  const tc = useTranslations("common");
  const [spec, setSpec] = useState<AgentSpec>(initial);
  const update = (changes: Partial<AgentSpec>) =>
    setSpec((current) => ({ ...current, ...changes }));

  const { capabilities } = useCapabilityCatalog();
  const { profiles, profilesStatus } = useModelProviders();
  const { skills, skillTotal, contextFiles, contextTotal, isLoading, error, refetch } =
    useInlineAgentResources();
  const { kbs: collections } = useKnowledgeBases();
  // Delegating and starting workflows are what a step's agent is not given: a
  // step is already a place in a graph of steps, and the graph - a workflow.run
  // step, with its loop and depth limits - is where work is handed on.
  const grantable = capabilities.filter((entry) => !NOT_IN_A_STEP.has(entry.id));

  return (
    <>
      <Tabs defaultValue="basics" className="flex min-h-0 flex-1 flex-col">
        <TabsList>
          <TabsTrigger value="basics">{t("inlineAgentTabBasics")}</TabsTrigger>
          <TabsTrigger value="tools">{t("inlineAgentTabTools")}</TabsTrigger>
          <TabsTrigger value="mcp">{t("inlineAgentTabMcp")}</TabsTrigger>
        </TabsList>
        <div className="min-h-0 flex-1 overflow-y-auto pt-4">
          <TabsContent value="basics" className="mt-0 space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="inline-agent-name">{t("inlineAgentName")}</Label>
              <Input
                id="inline-agent-name"
                value={spec.name}
                maxLength={128}
                onChange={(event) => update({ name: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("inlineAgentModel")}</Label>
              <ModelProfilePicker
                profiles={profiles}
                profilesStatus={profilesStatus}
                value={spec.model_profile_id ?? null}
                onChange={(model_profile_id) => update({ model_profile_id })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="inline-agent-instructions">{t("inlineAgentInstructions")}</Label>
              <Textarea
                id="inline-agent-instructions"
                rows={10}
                value={spec.instructions}
                placeholder={t("inlineAgentInstructionsPlaceholder")}
                onChange={(event) => update({ instructions: event.target.value })}
              />
            </div>
          </TabsContent>
          <TabsContent value="tools" className="mt-0">
            {error ? (
              <ErrorState
                cta={{
                  label: tc("retry"),
                  onClick: () => {
                    void refetch();
                  },
                }}
              />
            ) : isLoading ? (
              <LoadingState variant="skeleton-cards" />
            ) : (
              <CapabilityWorkbench
                // No notes to clear from here: the step's agent is created by its first run.
                agentId={null}
                catalog={grantable}
                selected={spec.capabilities}
                onToggle={(id) =>
                  update({
                    capabilities: withCapability(
                      spec.capabilities,
                      id,
                      !spec.capabilities.some((binding) => binding.id === id),
                    ),
                  })
                }
                onChange={(updated: CapabilityBindingSpec) =>
                  update({
                    capabilities: spec.capabilities.map((binding) =>
                      binding.id === updated.id ? updated : binding,
                    ),
                  })
                }
                subagents={[]}
                onSubagentsChange={() => undefined}
                // Delegation is not offered to a step's agent, so neither are remote delegates.
                externalAgents={[]}
                onExternalAgentsChange={() => undefined}
                resources={{
                  contextFiles,
                  contextTotal,
                  contextIds: spec.context_ids,
                  onContextToggle: (id: string) =>
                    update(withContextFiles(spec, toggled(spec.context_ids, id))),
                  collections,
                  collectionIds: spec.collection_ids,
                  onCollectionToggle: (id: string) =>
                    update({ collection_ids: toggled(spec.collection_ids, id) }),
                  skills,
                  skillTotal,
                  skillIds: spec.skill_ids,
                  onSkillToggle: (id: string) =>
                    update(withSkills(spec, toggled(spec.skill_ids, id))),
                }}
                modelProfileId={spec.model_profile_id ?? null}
              />
            )}
          </TabsContent>
          <TabsContent value="mcp" className="mt-0">
            <McpBindingsEditor spec={spec} onChange={update} />
          </TabsContent>
        </div>
      </Tabs>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          {tc("cancel")}
        </Button>
        <Button disabled={spec.name.trim() === ""} onClick={() => onSave(spec)}>
          {t("inlineAgentApply")}
        </Button>
      </DialogFooter>
    </>
  );
}
