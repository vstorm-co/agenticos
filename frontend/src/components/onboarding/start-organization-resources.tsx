"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { Button } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";

/** Organization setup never writes a person's composer or silently connects a private account. */
export function StartOrganizationResources({ kind }: { kind: "models" | "tools" }) {
  const t = useTranslations("start.scopes");
  const permissions = usePermissions();
  const common = useTranslations("common");
  if (permissions.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: common("retry"), onClick: () => void permissions.refetch() }}
      />
    );
  if (!permissions.isLoaded) return <LoadingState variant="pending" />;
  const canOpen =
    permissions.isLoaded &&
    !permissions.error &&
    permissions.can(kind === "models" ? Perm.secretsView : Perm.connectionsView);
  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-muted-foreground text-sm leading-relaxed">{t(`${kind}Shared`)}</p>
      {canOpen ? (
        <>
          <Button asChild variant="outline">
            <Link
              href={kind === "models" ? "/vault" : "/mcp-servers"}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t(kind === "models" ? "openVault" : "openConnections")}
              <ArrowUpRight className="size-4" aria-hidden />
            </Link>
          </Button>
          <p className="text-muted-foreground text-xs">{t("returnToSetup")}</p>
        </>
      ) : (
        <p role="status" className="text-muted-foreground text-sm">
          {t("resourcesPermission")}
        </p>
      )}
    </div>
  );
}
