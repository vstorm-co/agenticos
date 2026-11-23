"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useMuseAccount } from "@/hooks/use-muse-account";

export function MuseAccountControls({ id, keyOnly }: { id: string; keyOnly: boolean }) {
  const t = useTranslations("desktop.settings.externalAgents.account");
  const { action, progress, cancel, start } = useMuseAccount(id);
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={action.isPending}
          onClick={() => start("status")}
        >
          {t("status")}
        </Button>
        {!keyOnly && (
          <Button
            variant="outline"
            size="sm"
            disabled={action.isPending}
            onClick={() => start("sign_in")}
          >
            {t("signIn")}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={action.isPending}
          onClick={() => start("sign_out")}
        >
          {t("signOut")}
        </Button>
        {action.isPending && (
          <Button
            variant="ghost"
            size="sm"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {t("cancel")}
          </Button>
        )}
      </div>
      {action.data && (
        <p>
          {t(action.data.state)}
          {!action.data.credentialRequired && ` · ${t("keyless")}`}
        </p>
      )}
      {progress && (
        <div className="space-y-1" role="status">
          <a
            href={progress.verificationUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all underline"
          >
            {t("openSignIn")} · {new URL(progress.verificationUrl).hostname}
          </a>
          <p>
            {t("deviceCode")}: <code className="font-mono select-all">{progress.userCode}</code>
          </p>
          <p className="text-muted-foreground">{t("waiting")}</p>
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
