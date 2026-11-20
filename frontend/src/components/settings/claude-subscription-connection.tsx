"use client";

import { useTranslations } from "next-intl";
import { Badge, Button } from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useClaudeSubscription } from "@/hooks/use-claude-subscription";
import { usePermissions } from "@/hooks/use-permissions";
import { claudeSignInPending } from "@/lib/personal-subscriptions-api";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";
import { ClaudeSubscriptionLogin } from "./claude-subscription-login";
import { ClaudeSubscriptionModels } from "./claude-subscription-models";

export function ClaudeSubscriptionConnection() {
  const t = useTranslations("claudeSubscription");
  const user = useAuthStore((state) => state.user);
  const { can } = usePermissions();
  return (
    <section className="border-border space-y-3 rounded-xl border p-4">
      <h3
        className="flex flex-wrap items-center gap-2 text-sm font-medium"
        data-tour="claude-subscription-connect"
      >
        <ProviderIcon provider="anthropic" />
        {t("title")}
      </h3>
      <p className="text-muted-foreground text-sm">{t("description")}</p>
      {user && !user.impersonation && can(Perm.connectionsManage) ? (
        <ClaudeSubscriptionControls canReadModels={can(Perm.agentsView)} />
      ) : (
        <p className="text-muted-foreground text-xs">
          {t(user?.impersonation ? "ownSessionOnly" : "permission")}
        </p>
      )}
    </section>
  );
}

function ClaudeSubscriptionControls({ canReadModels }: { canReadModels: boolean }) {
  const t = useTranslations("claudeSubscription");
  const connection = useClaudeSubscription({ enabled: true });
  const { status, action, scope } = connection;
  const data = status.data;
  const loginId = data?.login_id;
  const retry = (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      loading={status.isFetching}
      onClick={() => void status.refetch()}
    >
      {t("retry")}
    </Button>
  );

  if (!connection.ready || status.isPending)
    return (
      <p role="status" className="text-muted-foreground text-xs">
        {t("checking")}
      </p>
    );
  if (status.isError || !data)
    return (
      <div role="alert" className="text-destructive text-sm">
        {t("statusFailed")}
        {retry}
      </div>
    );
  if (!data.available) return <p className="text-muted-foreground text-xs">{t("notConfigured")}</p>;

  return (
    <div className="space-y-3">
      {connection.failed && (
        <div role="alert" className="text-destructive text-sm">
          {t("requestFailed")}
          {retry}
        </div>
      )}
      {claudeSignInPending(data) && loginId != null ? (
        <ClaudeSubscriptionLogin
          key={`${scope}:${loginId}`}
          status={data}
          submitting={action === "submit"}
          cancelling={action === "cancel"}
          restarting={action === "start"}
          onSubmit={(code) => void connection.submit(loginId, code)}
          onCancel={() => void connection.cancel(loginId)}
          onRestart={() => void connection.start()}
        />
      ) : data.connected ? (
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="secondary">{t("connected")}</Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            loading={action === "disconnect"}
            onClick={() => void connection.disconnect()}
          >
            {t("disconnect")}
          </Button>
        </div>
      ) : (
        <>
          {data.state === "error" && (
            <p role="alert" className="text-destructive text-sm">
              {t("signInFailed")}
            </p>
          )}
          <Button
            type="button"
            size="sm"
            loading={action === "start"}
            disabled={action !== null}
            onClick={() => void connection.start()}
          >
            {t("connect")}
          </Button>
        </>
      )}
      <p className="text-muted-foreground text-xs">{t("supportedInputs")}</p>
      {canReadModels && !claudeSignInPending(data) && (
        <ClaudeSubscriptionModels
          key={scope}
          connected={data.connected}
          disabled={action !== null}
        />
      )}
    </div>
  );
}
