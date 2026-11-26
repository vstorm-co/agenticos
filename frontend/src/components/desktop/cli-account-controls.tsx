"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useCliAccount } from "@/hooks/use-cli-account";
import type { CliAccountAction } from "@/lib/desktop/commands";

export function CliAccountControls({ id }: { id: string }) {
  const t = useTranslations("desktop.settings.externalAgents.cliAccount");
  const { action, progress, cancel, start } = useCliAccount(id);
  const operations: CliAccountAction[] = ["status", "sign_in", "reconnect", "sign_out"];
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        {operations.map((operation) => (
          <Button
            key={operation}
            type="button"
            variant="outline"
            size="sm"
            disabled={
              action.isPending ||
              (operation === "sign_out" && action.data?.signOutAvailable === false)
            }
            onClick={() => start(operation)}
          >
            {t(operation)}
          </Button>
        ))}
        {action.isPending && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {t("cancel")}
          </Button>
        )}
      </div>
      {action.isPending && <p role="status">{t("waiting")}</p>}
      {action.data && <p role="status">{t(action.data.state)}</p>}
      {progress && (
        <div className="space-y-1" role="status">
          <a
            href={progress.verificationUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all underline"
          >
            {t("openSignIn")}
          </a>
          <p>
            {t("deviceCode")}: <code className="font-mono select-all">{progress.userCode}</code>
          </p>
        </div>
      )}
      {(action.error || cancel.error) && (
        <p role="alert" className="text-destructive">
          {t("failed")}
        </p>
      )}
    </div>
  );
}
