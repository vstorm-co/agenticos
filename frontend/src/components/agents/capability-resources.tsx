"use client";

import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { CollectionPicker } from "@/components/agents/collection-picker";
import { ContextGallery } from "@/components/agents/context-gallery";
import { SkillGallery } from "@/components/agents/skill-gallery";
import { CONTEXT_ID, KNOWLEDGE_ID, SKILLS_ID } from "@/lib/agent-spec";
import type { KnowledgeBase } from "@/types";
import type { ContextFileSummary, SkillSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

/**
 * What an agent is given, as opposed to what it may do.
 *
 * Three capabilities read something the organization owns - context files,
 * knowledge collections, skills - and all three keep their selection at the top
 * of the spec (`context_ids`, `collection_ids`, `skill_ids`) rather than in the
 * capability's config blob. One bundle so the workbench takes one prop for the
 * lot instead of twelve.
 */
export interface AgentResources {
  contextFiles: ContextFileSummary[];
  contextTotal: number;
  contextIds: string[];
  onContextToggle: (fileId: string) => void;
  collections: KnowledgeBase[];
  collectionIds: string[];
  onCollectionToggle: (collectionId: string) => void;
  skills: SkillSummary[];
  skillTotal: number;
  skillIds: string[];
  onSkillToggle: (skillId: string) => void;
}

/**
 * The picker a capability's Settings tab opens with, where it has one.
 *
 * Each of these used to be a card in a tab of its own - Knowledge and Skills had
 * a whole tab each, context shared the Skills one - two clicks from the switch
 * that decides whether any of it reaches the model. Which is the part that made
 * them findable by accident only: what the panel for "Knowledge search" offered
 * was a `top_k` field and a tool description, and the collections it searches
 * were somewhere else entirely.
 *
 * They live in Settings rather than beside the Tools tab because they are the
 * capability's subject: the tools are how the model reaches them.
 *
 * Returns null for a capability that reads nothing of the organization's, which
 * is most of them.
 */
export function CapabilityResources({
  capabilityId,
  enabled,
  resources,
  disabled,
}: {
  capabilityId: string;
  /** Whether the capability is granted - see the warning below. */
  enabled: boolean;
  resources: AgentResources;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");

  if (capabilityId === CONTEXT_ID) {
    return (
      <ResourceGroup
        heading={t("contextFilesHeading")}
        detail={t("contextFilesDetail")}
        warning={enabled || resources.contextIds.length === 0 ? null : t("contextOffButBound")}
      >
        <ContextGallery
          files={resources.contextFiles}
          total={resources.contextTotal}
          selectedIds={resources.contextIds}
          onToggle={resources.onContextToggle}
          disabled={disabled}
        />
      </ResourceGroup>
    );
  }

  if (capabilityId === KNOWLEDGE_ID) {
    return (
      <ResourceGroup
        heading={t("collectionsHeading")}
        detail={t("collectionsDetail")}
        warning={
          enabled || resources.collectionIds.length === 0 ? null : t("collectionsOffButBound")
        }
      >
        <CollectionPicker
          collections={resources.collections}
          selectedIds={resources.collectionIds}
          onToggle={resources.onCollectionToggle}
          disabled={disabled}
        />
      </ResourceGroup>
    );
  }

  if (capabilityId === SKILLS_ID) {
    return (
      <ResourceGroup
        heading={t("skillsHeading")}
        detail={t("skillsDetail")}
        warning={enabled || resources.skillIds.length === 0 ? null : t("skillsOffButBound")}
      >
        <SkillGallery
          skills={resources.skills}
          total={resources.skillTotal}
          selectedIds={resources.skillIds}
          onToggle={resources.onSkillToggle}
          disabled={disabled}
        />
      </ResourceGroup>
    );
  }

  return null;
}

/**
 * A picker under its own heading, with the one state no control here can state
 * alone: the spec still carries the selection, publish still checks it exists,
 * and with the capability off not one of them reaches a run. Silence there is how
 * "why does it not know the glossary" becomes unanswerable.
 */
function ResourceGroup({
  heading,
  detail,
  warning,
  children,
}: {
  heading: string;
  detail: string;
  warning: string | null;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      {warning !== null && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p className="text-xs">{warning}</p>
        </div>
      )}
      <div>
        <p className="text-sm font-medium">{heading}</p>
        <p className="text-muted-foreground text-xs">{detail}</p>
      </div>
      {children}
    </section>
  );
}
