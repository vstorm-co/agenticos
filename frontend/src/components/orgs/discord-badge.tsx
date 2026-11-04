"use client";

import { useTranslations } from "next-intl";

import { BrandIcon } from "@/components/icons/brand-icon";
import { Badge } from "@/components/ui";

/**
 * Marks a membership the Discord role sync made and maintains (#2569).
 *
 * The counterpart of `DirectoryBadge`, and explained by the caller for the same
 * reason: what the sync does to the row differs by where it is shown.
 */
export function DiscordBadge({ explanation }: { explanation: string }) {
  const t = useTranslations("discordRoles");
  return (
    <Badge variant="outline" title={explanation} className="text-muted-foreground font-normal">
      <BrandIcon name="discord" className="h-3 w-3" aria-hidden />
      <span>{t("badge")}</span>
      <span className="sr-only">{explanation}</span>
    </Badge>
  );
}
