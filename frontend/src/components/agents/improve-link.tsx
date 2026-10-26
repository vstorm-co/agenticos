"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImprovements } from "@/hooks/use-improvements";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { ROUTES } from "@/lib/constants";
import { resolvePreset } from "@/lib/dashboard/period";
import { openImprovement } from "@/lib/improvement-steps";

/**
 * Open the Improve wizard for this agent from a link. A link cannot know which
 * session is open, so the start screen it lands on forwards to one when there is.
 */
export function ImproveLink({
  agentId,
  className,
  children,
  "aria-label": label,
}: {
  agentId: string;
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
}) {
  return (
    <Link
      href={`${ROUTES.AGENT_DETAIL(agentId)}/improve/new?resume=1`}
      className={className}
      aria-label={label}
    >
      {children}
    </Link>
  );
}

/** Whether the agent had answers rated down or runs that failed in the last thirty days. */
export function useNeedsImprovement(agentId: string, { enabled }: { enabled: boolean }) {
  const lately = resolvePreset("30d");
  const { agents } = useAgentAttention({ from: lately.from, to: lately.to }, { enabled });
  const item = agents.find((agent) => agent.agent_id === agentId);
  return item !== undefined && (item.rated_down > 0 || item.failed_runs > 0);
}

/**
 * Improve, wherever an agent offers it: the session still open, or a new one in the
 * wizard. Primary when the agent needs it. Shown only to whoever may run the wizard -
 * edit access to the agent and runs:view - which the caller checks.
 */
export function ImproveButton({
  agentId,
  persist,
  size,
  tour,
}: {
  agentId: string;
  /** Store the page's draft first; false when it did not store. */
  persist?: () => Promise<boolean>;
  size?: "sm";
  tour?: string;
}) {
  const t = useTranslations("pages.agents");
  const router = useRouter();
  const needed = useNeedsImprovement(agentId, { enabled: true });
  const open = openImprovement(useImprovements(agentId).sessions);
  return (
    <Button
      size={size}
      data-tour={tour}
      variant={needed ? "default" : "outline"}
      className={needed ? "max-md:order-first" : undefined}
      onClick={() =>
        void (async () => {
          if (persist && !(await persist())) return;
          router.push(`${ROUTES.AGENT_DETAIL(agentId)}/improve/${open?.id ?? "new"}`);
        })()
      }
    >
      {t("improveSession")}
    </Button>
  );
}
