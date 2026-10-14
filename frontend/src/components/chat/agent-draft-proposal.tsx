"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { AvatarFace } from "@/components/ui/avatar-face";

import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useOrgStore } from "@/stores";
import { cn } from "@/lib/utils";

/**
 * The platform MCP tool that drafts an agent, as the run calls it.
 *
 * `agenticos` is the platform server's tool prefix (`PLATFORM_MCP_NAME` in
 * `backend/app/agents/mcp.py`) and `create_agent_draft` its tool.
 */
export const AGENT_DRAFT_TOOL = "agenticos_create_agent_draft";

interface DraftArgs {
  name: string;
  description: string | null;
  instructions: string;
  capabilities: string[];
}

/** The draft the call proposes, or null for arguments that are not one. */
export function draftArgs(args: Record<string, unknown> | undefined): DraftArgs | null {
  const { name, description, instructions, capabilities } = args ?? {};
  if (typeof name !== "string" || typeof instructions !== "string") return null;
  return {
    name,
    description: typeof description === "string" ? description : null,
    instructions,
    capabilities: Array.isArray(capabilities)
      ? capabilities.filter((id): id is string => typeof id === "string")
      : [],
  };
}

/**
 * An agent draft the AI Architect proposes, as the person approving it reads it (#1799).
 *
 * What is decided is the draft, so it is shown as one: which organization it is
 * created in, its name, what it may do in the capabilities' plain names, and the
 * instructions it starts from - rather than the JSON of a tool call. Approving
 * creates exactly this draft and publishes nothing.
 */
export function AgentDraftProposal({ draft }: { draft: DraftArgs }) {
  const t = useTranslations("chat");
  const guide = useCapabilityGuide();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: organizations = [] } = useOrganizationList();
  const organization = organizations.find((org) => org.id === activeOrgId)?.name ?? null;
  const [instructionsOpen, setInstructionsOpen] = useState(false);

  return (
    <div className="space-y-3 text-sm">
      {/* The agent as it will appear: the face its name will give it, and who it is. */}
      <div className="bg-foreground/[0.03] flex items-start gap-3 rounded-xl p-3">
        <span className="size-9 shrink-0">
          <AvatarFace seed={slugOf(draft.name)} />
        </span>
        <div className="min-w-0">
          <p className="text-foreground font-medium">{draft.name}</p>
          {draft.description && (
            <p className="text-muted-foreground text-[13px] leading-snug">{draft.description}</p>
          )}
          <p className="text-muted-foreground mt-1 text-xs">
            {organization === null
              ? t("draftProposalHere")
              : t("draftProposalIn", { organization })}
          </p>
        </div>
      </div>
      {draft.capabilities.length > 0 && (
        <div>
          <p className="text-muted-foreground text-xs font-medium">
            {t("draftProposalCapabilities")}
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-1">
            {draft.capabilities.map((id) => (
              <li key={id} className="bg-muted rounded-md px-2 py-0.5 text-xs">
                {guide(id)?.name ?? id}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="text-muted-foreground text-xs font-medium">
          {t("draftProposalInstructions")}
        </p>
        {/* Read as prose, which is what instructions are; folded to a few lines
            until somebody wants all of them. */}
        <p
          className={cn(
            "text-foreground/85 mt-1 text-[13px] leading-relaxed whitespace-pre-line",
            !instructionsOpen && "line-clamp-4",
          )}
        >
          {draft.instructions}
        </p>
        <button
          type="button"
          onClick={() => setInstructionsOpen(!instructionsOpen)}
          className="text-muted-foreground hover:text-foreground mt-1 text-xs font-medium"
        >
          {instructionsOpen ? t("showLess") : t("showMore")}
        </button>
      </div>
      <p className="text-muted-foreground text-xs">{t("draftProposalNotPublished")}</p>
    </div>
  );
}

/** The handle a name becomes, which seeds the face the agent will wear. */
function slugOf(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
