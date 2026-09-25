"use client";

import { Network } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";

/**
 * Marks a membership the directory sign-in sync made and maintains.
 *
 * The explanation is the caller's, because what the sync does to the row differs
 * by where it is shown - on an organization membership a hand-made role change
 * takes the row over, in a group it does not. It is a tooltip for a pointer and
 * text for a screen reader, since a `title` alone is read by neither reliably.
 */
export function DirectoryBadge({ explanation }: { explanation: string }) {
  const t = useTranslations("directory");
  return (
    <Badge variant="outline" title={explanation} className="text-muted-foreground font-normal">
      <Network className="h-3 w-3" aria-hidden />
      <span>{t("badge")}</span>
      <span className="sr-only">{explanation}</span>
    </Badge>
  );
}
