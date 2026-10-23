"use client";

import { useLocale, useTranslations } from "next-intl";

import type { ReachedAgent } from "@/types/authoring";

/**
 * Where applying a change to a context file or skill goes live at once: each
 * agent whose served version reads it, in which environments, behind which
 * eval suites - named for a reader of runs, counted for anybody else - and how
 * many more agents the reader may not see.
 */
export function GoesLive({ reaches, hidden }: { reaches: ReachedAgent[]; hidden: number }) {
  const t = useTranslations("authoring.goesLive");
  const locale = useLocale();
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const agents = reaches.map((agent) =>
    t("agent", {
      name: agent.name,
      environments: list.format(
        agent.environments.map((environment) =>
          environment.guards === 0
            ? environment.name
            : environment.guarded_by.length > 0
              ? t("guardedBy", {
                  name: environment.name,
                  suites: list.format(environment.guarded_by),
                })
              : t("guards", { name: environment.name, count: environment.guards }),
        ),
      ),
    }),
  );
  if (hidden > 0) agents.push(t("hidden", { count: hidden }));
  return (
    <p className="text-xs text-amber-700 dark:text-amber-400">
      {agents.length === 0 ? t("nowhere") : t("now", { agents: list.format(agents) })}
    </p>
  );
}
