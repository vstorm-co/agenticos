"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowUpRight, Check, Plug } from "lucide-react";

import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

interface StepToolsProps {
  tools: string[];
  onChange: (tools: string[]) => void;
}

// i18n-exempt: brand names
const COMMON_TOOLS = [
  { id: "github", label: "GitHub" }, // i18n-exempt: brand name
  { id: "slack", label: "Slack" }, // i18n-exempt: brand name
  { id: "google", label: "Google Drive" }, // i18n-exempt: brand name
  { id: "notion", label: "Notion" }, // i18n-exempt: brand name
  { id: "linear", label: "Linear" }, // i18n-exempt: brand name
  { id: "postgres", label: "PostgreSQL" }, // i18n-exempt: brand name
  { id: "hubspot", label: "HubSpot" }, // i18n-exempt: brand name
  { id: "zendesk", label: "Zendesk" }, // i18n-exempt: brand name
];

export function StepTools({ tools, onChange }: StepToolsProps) {
  const t = useTranslations("onboardingTeam");

  const toggleTool = (toolId: string) => {
    if (tools.includes(toolId)) {
      onChange(tools.filter((t) => t !== toolId));
    } else {
      onChange([...tools, toolId]);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{t("step3Title")}</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{t("step3Subtitle")}</p>
      </div>

      <div className="space-y-3">
        <label className="text-foreground text-sm font-medium">{t("toolsInStack")}</label>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {COMMON_TOOLS.map(({ id, label }) => {
            const selected = tools.includes(id);
            return (
              <button
                key={id}
                type="button"
                onClick={() => toggleTool(id)}
                className={cn(
                  "border-border bg-card hover:border-brand/40 flex items-center justify-between rounded-xl border p-3 text-left transition-all",
                  selected && "border-brand bg-brand/5 ring-brand/20 ring-1",
                )}
              >
                <span className="text-foreground text-xs font-medium">{label}</span>
                <div
                  className={cn(
                    "flex size-4 items-center justify-center rounded border transition-colors",
                    selected ? "border-brand bg-brand text-brand-foreground" : "border-border",
                  )}
                >
                  {selected && <Check className="size-3" />}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* App Authorization Box */}
      <section
        aria-labelledby="onboarding-apps-title"
        className="bg-card border-border space-y-4 rounded-2xl border p-5 sm:p-6"
      >
        <div className="flex items-start gap-4">
          <span className="bg-muted text-muted-foreground mt-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-xl">
            <Plug aria-hidden className="size-5" />
          </span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id="onboarding-apps-title" className="text-base font-medium">
                {t("appsTitle")}
              </h3>
              <Badge variant="secondary">{t("appsOptional")}</Badge>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">{t("appsDescription")}</p>
          </div>
        </div>

        <div className="flex flex-col items-start gap-3 border-t pt-4 sm:flex-row sm:items-center">
          <Button asChild variant="outline" size="sm">
            <Link href={ROUTES.CONNECTORS} target="_blank" rel="noopener noreferrer">
              {t("connectApps")}
              <ArrowUpRight aria-hidden />
            </Link>
          </Button>
          <p className="text-muted-foreground text-xs">{t("opensNewTab")}</p>
        </div>

        <p className="text-muted-foreground border-t pt-3 text-xs leading-relaxed">
          {t("skipHint")}
        </p>
      </section>
    </div>
  );
}
