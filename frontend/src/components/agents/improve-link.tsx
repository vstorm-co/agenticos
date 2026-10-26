"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { TrendingUp } from "lucide-react";

import { Button } from "@/components/ui";
import { useImprovements } from "@/hooks/use-improvements";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { attentionParts } from "@/lib/attention";
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

/**
 * Improve, wherever an agent offers it: the session still open, or a new one in the
 * wizard. Drawn like the buttons beside it; an agent with answers rated down or runs
 * that failed in the last thirty days wears a dot, and its name says why. Shown only
 * to whoever may run the wizard - edit access to the agent and runs:view - which the
 * caller checks.
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
  const tAttention = useTranslations("attention");
  const router = useRouter();
  const lately = resolvePreset("30d");
  const { agents } = useAgentAttention({ from: lately.from, to: lately.to });
  const attention = agents.find((agent) => agent.agent_id === agentId);
  const needed = attention !== undefined && (attention.rated_down > 0 || attention.failed_runs > 0);
  const open = openImprovement(useImprovements(agentId).sessions);
  return (
    <Button
      size={size}
      data-tour={tour}
      variant="outline"
      aria-label={
        needed
          ? tAttention("improveLabel", {
              reasons: attentionParts(attention, tAttention).join(", "),
            })
          : undefined
      }
      onClick={() =>
        void (async () => {
          if (persist && !(await persist())) return;
          router.push(`${ROUTES.AGENT_DETAIL(agentId)}/improve/${open?.id ?? "new"}`);
        })()
      }
    >
      <span className="relative" aria-hidden>
        <TrendingUp className="h-4 w-4" />
        {needed && (
          <span
            data-testid="improve-attention"
            className="bg-warning ring-background absolute -top-1 -right-1 size-2 rounded-full ring-2"
          />
        )}
      </span>
      {t("improveSession")}
    </Button>
  );
}
