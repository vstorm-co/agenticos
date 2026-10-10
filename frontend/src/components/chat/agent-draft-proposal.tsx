"use client";

import { useTranslations } from "next-intl";

import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useOrgStore } from "@/stores";

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

  return (
    <div className="space-y-2 text-sm">
      <p className="text-muted-foreground text-xs">
        {organization === null ? t("draftProposalHere") : t("draftProposalIn", { organization })}
      </p>
      <div>
        <p className="font-medium">{draft.name}</p>
        {draft.description && <p className="text-muted-foreground text-xs">{draft.description}</p>}
      </div>
      {draft.capabilities.length > 0 && (
        <div>
          <p className="text-muted-foreground text-xs">{t("draftProposalCapabilities")}</p>
          <ul className="mt-1 flex flex-wrap gap-1">
            {draft.capabilities.map((id) => (
              <li key={id} className="bg-muted rounded-md px-1.5 py-0.5 text-xs">
                {guide(id)?.name ?? id}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="text-muted-foreground text-xs">{t("draftProposalInstructions")}</p>
        <pre className="bg-muted text-foreground/90 mt-1 max-h-48 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap">
          {draft.instructions}
        </pre>
      </div>
      <p className="text-muted-foreground text-xs">{t("draftProposalNotPublished")}</p>
    </div>
  );
}
