"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  Building2,
  Check,
  Code2,
  Factory,
  HeartPulse,
  Landmark,
  Library,
  Loader2,
  Scale,
  ShoppingBag,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { useAgentTemplates } from "@/hooks/use-agent-templates";
import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import { useMcpCatalog } from "@/hooks/use-mcp-servers";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import type { AgentTemplate, TemplateIndustry } from "@/types/providers";

/** Icon per industry directory. An id with no entry falls back rather than blank. */
const INDUSTRY_ICONS: Record<string, LucideIcon> = {
  healthcare: HeartPulse,
  finance: Landmark,
  ecommerce: ShoppingBag,
  software: Code2,
  "public-sector": Building2,
  legal: Scale,
  manufacturing: Factory,
  general: Sparkles,
};

export function AgentTemplateDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("agentTemplates");
  const router = useRouter();
  const [industryId, setIndustryId] = useState<string | null>(null);

  const { industries, isLoading, isError, install, isInstalling, installingKey } =
    useAgentTemplates(open, (result) => {
      // Straight into the Builder: the agent is a draft that still needs a model
      // and, usually, a collection - so leaving the reader on a list would leave
      // them one click from an agent that cannot answer.
      onOpenChange(false);
      router.push(ROUTES.AGENT_DETAIL(result.agent_id));
    });

  const industry = industries.find((entry) => entry.id === industryId) ?? null;
  const setOpen = (next: boolean) => {
    setIndustryId(null);
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className={cn(DIALOG_FILL, DIALOG_CANVAS)}>
        <DialogHeader>
          <DialogTitle>{industry ? t(`industry.${industry.id}`) : t("title")}</DialogTitle>
          <DialogDescription>{industry ? t("industryHint") : t("description")}</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <LoadingState variant="skeleton-tiles" />
        ) : isError ? (
          <ErrorState />
        ) : industry ? (
          <IndustryTemplates
            industry={industry}
            onBack={() => setIndustryId(null)}
            onInstall={install}
            isInstalling={isInstalling}
            installingKey={installingKey}
          />
        ) : (
          <IndustryCards industries={industries} onPick={setIndustryId} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function IndustryCards({
  industries,
  onPick,
}: {
  industries: TemplateIndustry[];
  onPick: (id: string) => void;
}) {
  const t = useTranslations("agentTemplates");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="grid grid-cols-1 gap-4 p-1 sm:grid-cols-2 lg:grid-cols-3">
        {industries.map((industry) => {
          const Icon = INDUSTRY_ICONS[industry.id] ?? Library;
          return (
            <button
              key={industry.id}
              type="button"
              onClick={() => onPick(industry.id)}
              className="group hover:border-primary hover:bg-accent flex flex-col items-center gap-3 rounded-lg border p-8 text-center transition-colors"
            >
              <Icon className="text-muted-foreground group-hover:text-primary size-10 transition-colors" />
              <span className="font-medium">{t(`industry.${industry.id}`)}</span>
              <span className="text-muted-foreground text-sm">
                {t("count", { count: industry.templates.length })}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function IndustryTemplates({
  industry,
  onBack,
  onInstall,
  isInstalling,
  installingKey,
}: {
  industry: TemplateIndustry;
  onBack: () => void;
  onInstall: (key: string) => void;
  isInstalling: boolean;
  installingKey: string | undefined;
}) {
  const t = useTranslations("agentTemplates");

  return (
    <>
      <Button variant="ghost" size="sm" className="self-start" onClick={onBack}>
        <ArrowLeft className="mr-2 size-4" />
        {t("back")}
      </Button>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-1">
        {industry.templates.map((template) => (
          <TemplateRow
            key={template.key}
            template={template}
            busy={isInstalling && installingKey === template.key}
            disabled={isInstalling}
            onInstall={() => onInstall(template.key)}
          />
        ))}
      </div>
    </>
  );
}

function TemplateRow({
  template,
  busy,
  disabled,
  onInstall,
}: {
  template: AgentTemplate;
  busy: boolean;
  disabled: boolean;
  onInstall: () => void;
}) {
  const t = useTranslations("agentTemplates");
  const guide = useCapabilityGuide();
  const { servers } = useMcpCatalog();

  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{template.name}</span>
          {template.budget_usd !== null ? (
            <Badge variant="outline">{t("budget", { amount: template.budget_usd })}</Badge>
          ) : null}
        </div>
        <p className="text-muted-foreground text-sm">{template.description}</p>

        {/* Named the way the Toolbox names them, not by registry id. */}
        <div className="flex flex-wrap gap-1.5">
          {template.capabilities.map((id) => (
            <Badge key={id} variant="secondary">
              {guide(id)?.name ?? id}
            </Badge>
          ))}
        </div>

        {template.skills.length > 0 ? (
          <p className="text-muted-foreground text-xs">
            {t("bringsSkills", { count: template.skills.length })}
          </p>
        ) : null}
        {template.mcp.length > 0 ? (
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
            <span>{t("suggestsMcp")}</span>
            {template.mcp.map((key) => {
              const server = servers.find((entry) => entry.key === key);
              return (
                <span key={key} className="text-foreground inline-flex items-center gap-1.5">
                  <McpServerIcon
                    icon={server?.icon ?? null}
                    name={server?.name ?? key}
                    className="size-3.5"
                  />
                  {server?.name ?? key}
                </span>
              );
            })}
          </div>
        ) : null}
      </div>

      {template.installed ? (
        <span className="text-muted-foreground flex shrink-0 items-center gap-1.5 text-sm">
          <Check className="size-4" />
          {t("alreadyInstalled")}
        </span>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          disabled={disabled}
          onClick={onInstall}
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : t("use")}
        </Button>
      )}
    </div>
  );
}
