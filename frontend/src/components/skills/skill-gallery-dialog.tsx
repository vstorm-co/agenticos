"use client";

import { useState } from "react";
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
import { cn } from "@/lib/utils";
import { useSkillGallery } from "@/hooks/use-skill-gallery";
import type { GalleryIndustry } from "@/types/providers";

/**
 * Icon per industry id, keyed on the directory the backend ships.
 *
 * A table rather than a field on the response: the backend has no business
 * naming a component from an icon package, and an id it does not recognise
 * falls back rather than rendering nothing.
 */
const INDUSTRY_ICONS: Record<string, LucideIcon> = {
  healthcare: HeartPulse,
  finance: Landmark,
  ecommerce: ShoppingBag,
  software: Code2,
  "public-sector": Building2,
  legal: Scale,
  manufacturing: Factory,
};

function industryIcon(id: string): LucideIcon {
  return INDUSTRY_ICONS[id] ?? Library;
}

export function SkillGalleryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("skills.gallery");
  const [industryId, setIndustryId] = useState<string | null>(null);
  const { industries, isLoading, isError, install, isInstalling, installingKeys } =
    useSkillGallery(open);

  const industry = industries.find((entry) => entry.id === industryId) ?? null;
  // Back to the shelves on either edge, so reopening never lands the reader
  // inside whichever industry they last looked at.
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
          // Tiles, because the shelves are what loads first and the shape is
          // the caller's decision rather than the component's default.
          <LoadingState variant="skeleton-tiles" />
        ) : isError ? (
          <ErrorState />
        ) : industry ? (
          <IndustrySkills
            industry={industry}
            onBack={() => setIndustryId(null)}
            onInstall={install}
            isInstalling={isInstalling}
            installingKeys={installingKeys}
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
  industries: GalleryIndustry[];
  onPick: (id: string) => void;
}) {
  const t = useTranslations("skills.gallery");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="grid grid-cols-1 gap-4 p-1 sm:grid-cols-2 lg:grid-cols-3">
        {industries.map((industry) => {
          const Icon = industryIcon(industry.id);
          const remaining = industry.skills.filter((skill) => !skill.installed).length;
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
                {remaining === 0 ? t("allInstalled") : t("available", { count: remaining })}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function IndustrySkills({
  industry,
  onBack,
  onInstall,
  isInstalling,
  installingKeys,
}: {
  industry: GalleryIndustry;
  onBack: () => void;
  onInstall: (keys: string[]) => void;
  isInstalling: boolean;
  installingKeys: string[];
}) {
  const t = useTranslations("skills.gallery");
  const remaining = industry.skills.filter((skill) => !skill.installed);

  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="mr-2 size-4" />
          {t("back")}
        </Button>
        <Button
          size="sm"
          disabled={remaining.length === 0 || isInstalling}
          onClick={() => onInstall(remaining.map((skill) => skill.key))}
        >
          {t("installAll", { count: remaining.length })}
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-1">
        {industry.skills.map((skill) => {
          const busy = isInstalling && installingKeys.includes(skill.key);
          return (
            <div
              key={skill.key}
              className="flex items-start justify-between gap-4 rounded-lg border p-4"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{skill.name}</span>
                  {skill.category ? <Badge variant="outline">{skill.category}</Badge> : null}
                </div>
                <p className="text-muted-foreground text-sm">{skill.description}</p>
              </div>
              {skill.installed ? (
                <span className="text-muted-foreground flex shrink-0 items-center gap-1.5 text-sm">
                  <Check className="size-4" />
                  {t("alreadyInstalled")}
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  disabled={isInstalling}
                  onClick={() => onInstall([skill.key])}
                >
                  {busy ? <Loader2 className="size-4 animate-spin" /> : t("install")}
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
