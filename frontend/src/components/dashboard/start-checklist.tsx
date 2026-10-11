"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent } from "@/components/ui";
import {
  useAgents,
  useChannelBots,
  useGroups,
  useKnowledgeBases,
  useMembers,
  usePermissions,
} from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";

interface Step {
  id: string;
  done: boolean;
  href: string;
}

const dismissedKey = (orgId: string) => `agenticos:start-checklist:${orgId}`;

function readDismissed(orgId: string): boolean {
  try {
    return window.localStorage.getItem(dismissedKey(orgId)) === "dismissed";
  } catch {
    return false;
  }
}

/**
 * The first things worth doing in a new organization, with what is already done
 * ticked (#2072).
 *
 * For whoever builds agents, on the dashboard until every step is done or they
 * close it. Each step's state is read from what exists, not recorded, so doing a
 * step anywhere ticks it here. Closing it is a per-browser convenience.
 */
export function StartChecklist({ orgId }: { orgId: string }) {
  const { can } = usePermissions();
  return can(Perm.agentsEdit) ? <Checklist orgId={orgId} /> : null;
}

function Checklist({ orgId }: { orgId: string }) {
  const t = useTranslations("dashboard.startChecklist");
  const { can } = usePermissions();
  const [dismissed, setDismissed] = useState(() => readDismissed(orgId));
  const channels = can(Perm.channelsManage);
  const { agents, isLoading: agentsLoading } = useAgents();
  const { kbs } = useKnowledgeBases();
  const { groups } = useGroups(orgId);
  const { members } = useMembers(orgId);
  const { bots } = useChannelBots(channels);

  const steps: Step[] = [
    { id: "agent", done: agents.length > 0, href: ROUTES.AGENTS },
    {
      id: "publish",
      done: agents.some((agent) => agent.status === "published"),
      href: ROUTES.AGENTS,
    },
    { id: "knowledge", done: kbs.length > 0, href: ROUTES.RAG },
    { id: "departments", done: groups.length > 0, href: ROUTES.GROUPS },
    { id: "teammate", done: members.length > 1, href: ROUTES.ORG_MEMBERS(orgId) },
    ...(channels ? [{ id: "channel", done: bots.length > 0, href: ROUTES.CHANNELS }] : []),
  ];
  const left = steps.filter((step) => !step.done).length;
  const next = steps.find((step) => !step.done);

  if (dismissed || agentsLoading || left === 0) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(dismissedKey(orgId), "dismissed");
    } catch {
      // Nowhere to keep it; it stays closed for this visit.
    }
  };

  return (
    <Card className="mt-6">
      <CardContent className="space-y-3.5 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            <p className="text-muted-foreground text-xs">
              {t("progress", { done: steps.length - left, total: steps.length })}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={t("dismiss")}
            onClick={dismiss}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div
          className="bg-muted h-1 overflow-hidden rounded-full"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={steps.length - left}
          aria-label={t("title")}
        >
          <div
            className="bg-success h-full rounded-full transition-[width]"
            style={{ width: `${((steps.length - left) / steps.length) * 100}%` }}
          />
        </div>
        {/* The one thing to do next, said once and plainly; the rest is a
            compact record rather than six boxes with lines through them. */}
        {next && (
          <Link
            href={next.href}
            className="group bg-muted/60 hover:bg-accent flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors"
          >
            <span className="min-w-0">
              <span aria-hidden className="text-muted-foreground block text-xs">
                {t("next")}
              </span>
              <span className="font-medium">{t(`steps.${next.id}`)}</span>
            </span>
            <ArrowRight
              className="text-muted-foreground group-hover:text-foreground h-4 w-4 shrink-0 transition-colors"
              aria-hidden
            />
          </Link>
        )}
        <ol className="flex flex-wrap gap-x-4 gap-y-1.5">
          {steps
            .filter((step) => step !== next)
            .map((step) => (
              <li key={step.id}>
                <Link
                  href={step.href}
                  className={cn(
                    "hover:text-foreground flex items-center gap-1.5 text-xs transition-colors",
                    step.done ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border",
                      step.done && "bg-success border-success text-white",
                    )}
                  >
                    {step.done && <Check className="h-2.5 w-2.5" aria-hidden />}
                    {step.done && <span className="sr-only">{t("doneLabel")}</span>}
                  </span>
                  {t(`steps.${step.id}`)}
                </Link>
              </li>
            ))}
        </ol>
      </CardContent>
    </Card>
  );
}
