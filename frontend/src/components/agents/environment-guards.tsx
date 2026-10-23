"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useEvalSuites } from "@/hooks/use-eval-suites";
import type { AgentEnvironment } from "@/types/agents";

/**
 * Which of the agent's eval suites an environment requires to pass on a version
 * before it takes it.
 *
 * Taking a guard off lets through what it would have stopped, so only somebody
 * who may override promotions changes the set; everybody else reads it.
 */
export function EnvironmentGuards({
  agentId,
  environment,
  canEdit,
  saving,
  onSave,
}: {
  agentId: string;
  environment: AgentEnvironment;
  canEdit: boolean;
  saving: boolean;
  onSave: (suiteIds: string[]) => void;
}) {
  const t = useTranslations("promotionGate");
  const { suites } = useEvalSuites(agentId);
  const [chosen, setChosen] = useState<string[]>(environment.guard_suite_ids);
  const changed =
    chosen.length !== environment.guard_suite_ids.length ||
    chosen.some((id) => !environment.guard_suite_ids.includes(id));

  if (suites.length === 0) {
    return <p className="text-muted-foreground text-xs">{t("noSuites")}</p>;
  }
  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">{t("guardsHelp", { name: environment.name })}</p>
      <ul className="space-y-1.5">
        {suites.map((suite) => {
          // A guard is pinned to a dataset version, so one on a dataset with none cannot be set.
          const empty = suite.dataset_has_cases === false && !chosen.includes(suite.id);
          return (
            <li key={suite.id} className="space-y-0.5">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={chosen.includes(suite.id)}
                  disabled={!canEdit || empty}
                  onCheckedChange={(checked) =>
                    setChosen((current) =>
                      checked === true
                        ? [...current, suite.id]
                        : current.filter((id) => id !== suite.id),
                    )
                  }
                />
                {suite.name}
              </label>
              {empty && <p className="text-muted-foreground pl-6 text-xs">{t("noCasesYet")}</p>}
            </li>
          );
        })}
      </ul>
      {canEdit ? (
        <Button size="sm" disabled={!changed || saving} onClick={() => onSave(chosen)}>
          {t("storeGuards")}
        </Button>
      ) : (
        <p className="text-muted-foreground text-xs">{t("guardsReadOnly")}</p>
      )}
    </div>
  );
}
