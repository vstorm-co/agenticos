"use client";

import { useTranslations } from "next-intl";
import {
  Briefcase,
  Building2,
  Code2,
  Cpu,
  Factory,
  Headphones,
  HeartPulse,
  Landmark,
  Scale,
  Settings2,
  ShoppingCart,
  Users,
  Workflow,
} from "lucide-react";

import { cn } from "@/lib/utils";

interface StepAboutProps {
  role: string;
  industry: string;
  teamSize: string;
  onChange: (fields: { role?: string; industry?: string; teamSize?: string }) => void;
}

const ROLES = [
  { id: "founder", icon: Building2 },
  { id: "engineering", icon: Code2 },
  { id: "product", icon: Workflow },
  { id: "operations", icon: Settings2 },
  { id: "support", icon: Headphones },
  { id: "legal", icon: Scale },
  { id: "other", icon: Users },
] as const;

const INDUSTRIES = [
  { id: "software", icon: Cpu },
  { id: "ecommerce", icon: ShoppingCart },
  { id: "finance", icon: Landmark },
  { id: "healthcare", icon: HeartPulse },
  { id: "legal", icon: Scale },
  { id: "manufacturing", icon: Factory },
  { id: "public-sector", icon: Landmark, key: "publicSector" },
  { id: "general", icon: Briefcase },
] as const;

const TEAM_SIZES = [
  { id: "solo", labelKey: "teamSizes.solo", descKey: "teamSizes.soloDesc" },
  { id: "small", labelKey: "teamSizes.small", descKey: "teamSizes.smallDesc" },
  { id: "company", labelKey: "teamSizes.company", descKey: "teamSizes.companyDesc" },
] as const;

export function StepAbout({ role, industry, teamSize, onChange }: StepAboutProps) {
  const t = useTranslations("onboardingTeam");

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{t("step1Title")}</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{t("step1Subtitle")}</p>
      </div>

      {/* Role */}
      <div className="space-y-3">
        <label className="text-foreground text-sm font-medium">{t("roleLabel")}</label>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4">
          {ROLES.map(({ id, icon: Icon }) => {
            const selected = role === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onChange({ role: id })}
                className={cn(
                  "border-border bg-card hover:border-brand/40 flex flex-col items-start gap-2.5 rounded-xl border p-3.5 text-left transition-all",
                  selected && "border-brand bg-brand/5 ring-brand/20 ring-1",
                )}
              >
                <div
                  className={cn(
                    "flex size-8 items-center justify-center rounded-lg border",
                    selected
                      ? "border-brand/30 bg-brand text-brand-foreground"
                      : "border-border/60 bg-muted/50 text-muted-foreground",
                  )}
                >
                  <Icon className="size-4" />
                </div>
                <span className="text-foreground text-xs font-medium">{t(`roles.${id}`)}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Industry */}
      <div className="space-y-3">
        <label className="text-foreground text-sm font-medium">{t("industryLabel")}</label>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4">
          {INDUSTRIES.map((item) => {
            const selected = industry === item.id;
            const key = "key" in item ? item.key : item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onChange({ industry: item.id })}
                className={cn(
                  "border-border bg-card hover:border-brand/40 flex flex-col items-start gap-2.5 rounded-xl border p-3.5 text-left transition-all",
                  selected && "border-brand bg-brand/5 ring-brand/20 ring-1",
                )}
              >
                <div
                  className={cn(
                    "flex size-8 items-center justify-center rounded-lg border",
                    selected
                      ? "border-brand/30 bg-brand text-brand-foreground"
                      : "border-border/60 bg-muted/50 text-muted-foreground",
                  )}
                >
                  <item.icon className="size-4" />
                </div>
                <span className="text-foreground text-xs font-medium">
                  {t(`industries.${key}`)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Team Size */}
      <div className="space-y-3">
        <label className="text-foreground text-sm font-medium">{t("teamSizeLabel")}</label>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          {TEAM_SIZES.map(({ id, labelKey, descKey }) => {
            const selected = teamSize === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onChange({ teamSize: id })}
                className={cn(
                  "border-border bg-card hover:border-brand/40 flex items-center justify-between rounded-xl border p-3.5 text-left transition-all",
                  selected && "border-brand bg-brand/5 ring-brand/20 ring-1",
                )}
              >
                <div className="space-y-0.5">
                  <div className="text-foreground text-xs font-medium">{t(labelKey)}</div>
                  <div className="text-muted-foreground text-[11px]">{t(descKey)}</div>
                </div>
                <div
                  className={cn(
                    "size-3.5 rounded-full border",
                    selected ? "border-brand bg-brand" : "border-border",
                  )}
                />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
