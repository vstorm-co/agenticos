"use client";

import Link from "next/link";
import { Play } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { ArtifactActionView } from "@/types/artifact";

/**
 * "This page can run: X, Y" in the viewer's strip: the workflows the page may ask
 * to start for this person, each a link to that workflow's runs. Nothing without
 * actions - a page that cannot run anything has nothing to announce.
 *
 * Names are the workflows' own, never the page's labels.
 */
export function ArtifactActionsMenu({ actions }: { actions: readonly ArtifactActionView[] }) {
  const t = useTranslations("artifacts");
  if (actions.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="max-w-[16rem]"
          data-tour="artifact-actions"
          aria-label={t("actions.canRun", {
            names: actions.map((action) => action.name).join(", "),
          })}
        >
          <Play className="h-3.5 w-3.5 shrink-0" />
          <span className="sr-only truncate sm:not-sr-only" aria-hidden>
            {t("actions.canRun", { names: actions.map((action) => action.name).join(", ") })}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t("actions.runsOf")}</DropdownMenuLabel>
        {actions.map((action) => (
          <DropdownMenuItem key={action.workflow_id} asChild>
            <Link href={ROUTES.WORKFLOW_RUNS(action.workflow_id)}>{action.name}</Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
