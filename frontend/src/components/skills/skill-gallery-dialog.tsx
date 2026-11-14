"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  ArrowLeft,
  Building2,
  Check,
  ChevronDown,
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
  Skeleton,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { DiffView } from "@/components/authoring/diff-view";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import {
  DIALOG_BROAD,
  DIALOG_CANVAS,
  DIALOG_COLUMN,
  DIALOG_FILL,
  DIALOG_SCROLL_GUTTER,
} from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useGallerySkillPreview, useSkillGallery } from "@/hooks/use-skill-gallery";
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
      <DialogContent
        className={cn(industry ? [DIALOG_FILL, DIALOG_CANVAS] : [DIALOG_COLUMN, DIALOG_BROAD])}
      >
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
    <div className={cn("min-h-0 flex-1 overflow-y-auto", DIALOG_SCROLL_GUTTER)}>
      <div className="grid grid-cols-1 gap-4 p-1 sm:grid-cols-2 lg:grid-cols-3">
        {industries.map((industry) => {
          const Icon = industryIcon(industry.id);
          const remaining = industry.skills.filter((skill) => !skill.installed).length;
          return (
            <button
              key={industry.id}
              type="button"
              onClick={() => onPick(industry.id)}
              className="group bg-muted hover:bg-accent focus-visible:ring-ring/40 grid grid-cols-[2rem_minmax(0,1fr)] items-center gap-x-3 gap-y-1 rounded-lg border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none sm:flex sm:flex-col sm:gap-2 sm:p-5 sm:text-center"
            >
              <Icon className="text-muted-foreground group-hover:text-primary row-span-3 size-7 transition-colors sm:size-8" />
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
  const [previewed, setPreviewed] = useState<string | null>(null);

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

      <div className={cn("min-h-0 flex-1 space-y-3 overflow-y-auto p-1", DIALOG_SCROLL_GUTTER)}>
        {industry.skills.map((skill) => {
          const busy = isInstalling && installingKeys.includes(skill.key);
          return (
            <div key={skill.key} className="bg-muted space-y-3 rounded-lg border p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{skill.name}</span>
                    {skill.category ? <Badge variant="outline">{skill.category}</Badge> : null}
                  </div>
                  <p className="text-muted-foreground text-sm">{skill.description}</p>
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0"
                    aria-expanded={previewed === skill.key}
                    onClick={() => setPreviewed(previewed === skill.key ? null : skill.key)}
                  >
                    <ChevronDown className="size-4" aria-hidden />
                    {previewed === skill.key ? t("hidePreview") : t("preview")}
                  </Button>
                </div>
                {skill.installed && skill.installed_id ? (
                  <Link
                    href={ROUTES.SKILL_DETAIL(skill.installed_id)}
                    className="text-muted-foreground hover:text-foreground flex shrink-0 items-center gap-1.5 text-sm underline-offset-4 hover:underline"
                  >
                    <Check className="size-4" />
                    {t("alreadyInstalled")}
                  </Link>
                ) : skill.installed ? (
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
              {previewed === skill.key && <GalleryPreview skillKey={skill.key} />}
            </div>
          );
        })}
      </div>
    </>
  );
}

/** A gallery skill's instructions and files, read before it is installed. */
function GalleryPreview({ skillKey }: { skillKey: string }) {
  const t = useTranslations("skills.gallery");
  const tErrors = useTranslations("errors");
  const { preview, error } = useGallerySkillPreview(skillKey);
  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (!preview) return <Skeleton className="h-24 w-full" />;
  return (
    <div className="space-y-2">
      <DiffView before={preview.content} after={preview.content} modes={false} />
      {preview.files.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("files", { count: preview.files.length, names: preview.files.join(", ") })}
        </p>
      )}
    </div>
  );
}
