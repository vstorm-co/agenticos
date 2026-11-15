"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Bot, Plus, Sparkles, Trash2, Workflow } from "lucide-react";

import { Badge, Button } from "@/components/ui";
import type { OnboardingTeamProposal, ProposedSpecialist } from "@/types/onboarding";

interface StepTeamProps {
  proposal: OnboardingTeamProposal;
  onUpdateLeadName: (name: string) => void;
  onRemoveSpecialist: (index: number) => void;
  onAddSpecialist: (specialist: ProposedSpecialist) => void;
  onDeploy: () => void;
  isDeploying: boolean;
}

// i18n-exempt: catalog template presets
const TEMPLATE_ADD_OPTIONS: ProposedSpecialist[] = [
  {
    key: "general/agenticos",
    name: "General Assistant", // i18n-exempt: preset name
    role: "Tasks & Q&A", // i18n-exempt: preset role
    description: "Researches questions, writes documents, and coordinates general tasks.", // i18n-exempt: preset desc
    capabilities: ["web_research", "visuals", "artifacts"],
    recommended: false,
  },
  {
    key: "general/platform-assistant",
    name: "Platform Architect", // i18n-exempt: preset name
    role: "Agent & Workflow Builder", // i18n-exempt: preset role
    description: "Helps design, configure, test, and tune agents and workflows.", // i18n-exempt: preset desc
    capabilities: ["skills", "visuals", "artifacts"],
    recommended: false,
  },
  {
    key: "software/release-writer",
    name: "Release Notes Writer", // i18n-exempt: preset name
    role: "Product Updates", // i18n-exempt: preset role
    description: "Summarizes merged changes into user-facing release notes.", // i18n-exempt: preset desc
    capabilities: ["artifacts"],
    recommended: false,
  },
  {
    key: "ecommerce/order-support",
    name: "Order Support", // i18n-exempt: preset name
    role: "Customer Orders", // i18n-exempt: preset role
    description: "Answers order status, delivery, and return inquiries.", // i18n-exempt: preset desc
    capabilities: ["artifacts"],
    recommended: false,
  },
  {
    key: "legal/contract-reviewer",
    name: "Contract First Pass", // i18n-exempt: preset name
    role: "Agreement Review", // i18n-exempt: preset role
    description: "Analyzes contracts and flags liability and compliance terms.", // i18n-exempt: preset desc
    capabilities: ["artifacts"],
    recommended: false,
  },
];

export function StepTeam({
  proposal,
  onUpdateLeadName,
  onRemoveSpecialist,
  onAddSpecialist,
  onDeploy,
  isDeploying,
}: StepTeamProps) {
  const t = useTranslations("onboardingTeam");
  const [showAddMenu, setShowAddMenu] = useState(false);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{t("step4Title")}</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{t("step4Subtitle")}</p>
      </div>

      {/* Rationale Callout */}
      {proposal.rationale && (
        <div className="border-brand/20 bg-brand/5 text-foreground flex items-start gap-3 rounded-2xl border p-4 text-xs leading-relaxed">
          <Sparkles className="text-brand mt-0.5 size-4 shrink-0" />
          <p>{proposal.rationale}</p>
        </div>
      )}

      {/* Lead Orchestrator Card */}
      <div className="border-brand/40 bg-card relative space-y-4 rounded-2xl border p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="bg-brand text-brand-foreground inline-flex size-10 shrink-0 items-center justify-center rounded-xl shadow-sm">
              <Workflow className="size-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={proposal.lead.name}
                  onChange={(e) => onUpdateLeadName(e.target.value)}
                  className="text-foreground hover:border-border focus:border-brand border-b border-transparent bg-transparent px-1 py-0.5 text-base font-semibold transition-colors focus:outline-none"
                />
              </div>
              <p className="text-muted-foreground text-xs">{proposal.lead.role}</p>
            </div>
          </div>
          <Badge variant="default" className="bg-brand/10 text-brand border-brand/20 border">
            {t("leadBadge")}
          </Badge>
        </div>

        <p className="text-muted-foreground text-sm leading-relaxed">{proposal.lead.description}</p>

        {/* Lead Starters */}
        {proposal.lead.starters.length > 0 && (
          <div className="border-border/60 space-y-1.5 border-t pt-3">
            <span className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
              {t("starterPromptsHeader")}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {proposal.lead.starters.map((starter, i) => (
                <span
                  key={i}
                  className="bg-muted text-muted-foreground inline-block rounded-md px-2.5 py-1 text-xs"
                >
                  &quot;{starter}&quot;
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Specialists Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-foreground text-sm font-semibold tracking-tight">
            {t("specialistsTitle")} ({proposal.specialists.length})
          </h3>
          <div className="relative">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowAddMenu(!showAddMenu)}
              className="gap-1.5 text-xs"
            >
              <Plus className="size-3.5" />
              {t("addSpecialist")}
            </Button>

            {showAddMenu && (
              <div className="border-border bg-popover text-popover-foreground absolute right-0 z-20 mt-2 w-72 space-y-1 rounded-xl border p-2 shadow-lg">
                <div className="text-muted-foreground px-2 py-1 text-[11px] font-medium">
                  {t("selectTemplate")}
                </div>
                {TEMPLATE_ADD_OPTIONS.map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      onAddSpecialist(item);
                      setShowAddMenu(false);
                    }}
                    className="hover:bg-accent flex w-full flex-col items-start gap-0.5 rounded-lg p-2 text-left transition-colors"
                  >
                    <span className="text-foreground text-xs font-medium">{item.name}</span>
                    <span className="text-muted-foreground line-clamp-1 text-[11px]">
                      {item.description}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {proposal.specialists.map((specialist, idx) => (
            <div
              key={idx}
              className="border-border bg-card flex flex-col justify-between rounded-xl border p-4 transition-all hover:shadow-sm"
            >
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-lg">
                      <Bot className="size-4" />
                    </span>
                    <div>
                      <h4 className="text-foreground text-xs font-semibold">{specialist.name}</h4>
                      <p className="text-muted-foreground text-[11px]">{specialist.role}</p>
                    </div>
                  </div>
                  {proposal.specialists.length > 1 && (
                    <button
                      type="button"
                      onClick={() => onRemoveSpecialist(idx)}
                      aria-label={`${t("removeSpecialist")} ${specialist.name}`}
                      className="text-muted-foreground hover:text-destructive p-1 transition-colors"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </div>

                <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
                  {specialist.description}
                </p>
              </div>

              {specialist.capabilities.length > 0 && (
                <div className="border-border/60 mt-3 flex flex-wrap gap-1 border-t pt-2.5">
                  {specialist.capabilities.slice(0, 3).map((cap, i) => (
                    <span
                      key={i}
                      className="bg-muted/80 text-muted-foreground rounded px-1.5 py-0.5 text-[10px]"
                    >
                      {cap}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Deploy Button */}
      <div className="flex justify-end pt-4">
        <Button
          type="button"
          onClick={onDeploy}
          disabled={isDeploying || proposal.specialists.length === 0}
          className="gap-2 px-6"
        >
          <Sparkles className="size-4" />
          {t("deployTeam")}
        </Button>
      </div>
    </div>
  );
}
