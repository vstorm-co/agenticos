"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSystemAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { AgentCard } from "./agent-card";

/**
 * The platform's own agents, folded away under the organization's.
 *
 * Nothing here is chatted with, put on a channel or delegated to, so the cards
 * carry no menu to duplicate, archive or delete one: `agents:edit` opens it to
 * change its instructions, model and budget. Absent while the organization has none.
 */
export function SystemAgentsSection() {
  const t = useTranslations("agents");
  const { agents, total } = useSystemAgents();
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  if (total === 0) return null;

  return (
    <section className="space-y-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm font-medium"
      >
        <ChevronRight
          className={cn("h-4 w-4 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        {t("systemAgents", { count: total })}
      </button>
      {open && (
        <>
          <p className="text-muted-foreground text-xs">{t("systemAgentsHint")}</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} canEdit={can(Perm.agentsEdit)} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
