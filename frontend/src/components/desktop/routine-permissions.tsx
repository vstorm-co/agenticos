"use client";

import { useTranslations } from "next-intl";

import { SectionCard } from "@/components/settings/settings-section";
import { Button } from "@/components/ui";
import { useRoutineLocalWork } from "@/hooks/use-routine-local-work";

export function RoutinePermissions() {
  const t = useTranslations("triggers.local");
  const { available, grants, revoke } = useRoutineLocalWork();
  if (!available) return null;
  return (
    <SectionCard title={t("permissionsTitle")} description={t("permissionsDescription")}>
      {grants.isError ? (
        <p className="text-destructive text-sm">{t("permissionFailed")}</p>
      ) : grants.isPending ? null : grants.data?.length ? (
        <ul className="space-y-3">
          {grants.data.map((grant) => (
            <li key={grant.id} className="flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium">{grant.name}</p>
                <p className="text-muted-foreground truncate" title={grant.root}>
                  {grant.root}
                </p>
                <p className="text-muted-foreground text-xs">
                  {[
                    t("read"),
                    ...(grant.operations.write ? [t("write")] : []),
                    ...(grant.operations.execute ? [t("execute")] : []),
                  ].join(" · ")}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(grant.id)}
              >
                {t("revoke")}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-sm">{t("noPermissions")}</p>
      )}
    </SectionCard>
  );
}
