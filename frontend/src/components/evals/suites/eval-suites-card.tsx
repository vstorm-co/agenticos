"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useEvalSuites } from "@/hooks/use-eval-suites";
import { getErrorMessage } from "@/lib/api-error";
import { SuiteFormDialog } from "./suite-form-dialog";
import { SuiteRow } from "./suite-row";

/**
 * The agent's eval suites, under its runs on the Evals tab: each dataset it is
 * held to, when that runs on its own, what a result must meet, and how it last
 * came out.
 *
 * The description already says what a suite does, so having none is one line
 * rather than a panel pushing the runs below the fold. `canManage` hides the
 * create button and each row's actions for a caller who may not save a suite;
 * the server refuses them anyway.
 */
export function EvalSuitesCard({ agentId, canManage }: { agentId: string; canManage: boolean }) {
  const t = useTranslations("evals.suites");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const { suites, isPending, error, refetch } = useEvalSuites(agentId);
  const [creating, setCreating] = useState(false);
  const create = canManage ? { label: t("new"), onClick: () => setCreating(true) } : undefined;

  return (
    <Card>
      <CardHeader
        data-tour="agent-eval-suites"
        className="flex flex-row items-start justify-between gap-4 space-y-0"
      >
        <div className="space-y-1.5">
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </div>
        {create && suites.length > 0 && (
          <Button size="sm" variant="outline" onClick={create.onClick}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {create.label}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {isPending ? (
          <LoadingState variant="skeleton-list" rows={2} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : suites.length === 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-muted-foreground text-sm">{t("empty.line")}</p>
            {create && (
              <Button size="sm" variant="outline" onClick={create.onClick}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {create.label}
              </Button>
            )}
          </div>
        ) : (
          suites.map((suite) => <SuiteRow key={suite.id} suite={suite} canManage={canManage} />)
        )}
      </CardContent>
      {creating && <SuiteFormDialog agentId={agentId} onOpenChange={setCreating} />}
    </Card>
  );
}
