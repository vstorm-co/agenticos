"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Check, Copy, ExternalLink } from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  IconButton,
  Input,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SubscriptionAccountUsage } from "@/components/agents/subscription-account-usage";
import { SectionCard } from "@/components/settings/settings-section";
import { ProviderIcon } from "@/components/vault/provider-icon";
import {
  useSubscriptionAccounts,
  useSubscriptionSignInStatus,
} from "@/hooks/use-subscription-accounts";
import { getErrorMessage } from "@/lib/api-error";
import {
  SUBSCRIPTION_PROVIDERS,
  SUBSCRIPTION_MARK,
  subscriptionBelongsTo,
  type SubscriptionProvider,
  type SubscriptionSignIn,
} from "@/lib/subscription-accounts-api";

/** A person's own subscription accounts, which models on "Subscription accounts" run on. */
export function SubscriptionAccounts() {
  const t = useTranslations("subscriptionAccounts");
  const errors = useTranslations("errors");
  const actions = useSubscriptionAccounts();
  const [connecting, setConnecting] = useState<SubscriptionProvider | null>(null);
  const listed = actions.accounts.data;
  if (listed !== undefined && !listed.enabled) return null;
  const rows = listed?.items ?? [];
  const providers = [...SUBSCRIPTION_PROVIDERS].sort(
    (a, b) =>
      Number(rows.some((account) => subscriptionBelongsTo(account, b))) -
      Number(rows.some((account) => subscriptionBelongsTo(account, a))),
  );
  const failure = (error: unknown) => toast.error(getErrorMessage(error, errors));
  return (
    <SectionCard
      title={t("title")}
      description={<p>{t("description")}</p>}
      tour="personal-subscription-accounts"
    >
      {actions.accounts.error ? (
        <ErrorState
          title={t("loadFailed")}
          cta={{ label: t("retry"), onClick: () => void actions.accounts.refetch() }}
        />
      ) : (
        <ul className="divide-border divide-y">
          {providers.map((provider) => {
            const accounts = rows.filter((account) => subscriptionBelongsTo(account, provider));
            return (
              <li key={provider} className="flex flex-wrap items-start justify-between gap-3 py-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <span className="bg-muted grid size-9 shrink-0 place-items-center rounded-lg">
                    <ProviderIcon provider={SUBSCRIPTION_MARK[provider]} className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm font-medium">{t(`providers.${provider}`)}</p>
                    {accounts.length === 0 && (
                      <p className="text-muted-foreground text-xs">{t("notConnected")}</p>
                    )}
                    {accounts.map((account) => (
                      <div key={account.name} className="space-y-2 py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-xs">
                            {account.email ?? account.label ?? account.name}
                          </span>
                          {(account.disabled || account.unavailable) && (
                            <Badge variant="outline">{t("unavailable")}</Badge>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            disabled={actions.disconnect.isPending}
                            onClick={() =>
                              void actions.disconnect.mutateAsync(account.name).catch(failure)
                            }
                          >
                            {t("disconnect")}
                          </Button>
                        </div>
                        <SubscriptionAccountUsage account={account} />
                      </div>
                    ))}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!actions.ready || actions.accounts.isLoading}
                  onClick={() => setConnecting(provider)}
                >
                  {accounts.length > 0 ? t("connectAnother") : t("connect")}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <p role="note" className="text-muted-foreground mt-4 text-xs">
        {t("risk")}
      </p>
      {connecting && (
        <SubscriptionSignInDialog
          key={`${actions.scope}:${connecting}`}
          provider={connecting}
          actions={actions}
          onClose={() => setConnecting(null)}
        />
      )}
    </SectionCard>
  );
}

type Actions = ReturnType<typeof useSubscriptionAccounts>;

export function SubscriptionSignInDialog({
  provider,
  actions,
  onClose,
}: {
  provider: SubscriptionProvider;
  actions: Actions;
  onClose: () => void;
}) {
  const t = useTranslations("subscriptionAccounts");
  const errors = useTranslations("errors");
  const common = useTranslations("common");
  const formId = useId();
  const [started, setStarted] = useState<SubscriptionSignIn | null>(null);
  const [redirectUrl, setRedirectUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const status = useSubscriptionSignInStatus(actions.scope, started?.state ?? null);
  const finished = status.data?.status === "ok";
  const refused = status.data?.status === "error";
  const name = t(`providers.${provider}`);

  // Start once, when the dialog opens; the effect's own flag survives a re-render.
  const start = actions.start.mutateAsync;
  const begun = useRef(false);
  useEffect(() => {
    if (begun.current) return;
    begun.current = true;
    start(provider)
      .then(setStarted)
      .catch((error: unknown) => {
        toast.error(getErrorMessage(error, errors));
        onClose();
      });
  }, [start, provider, errors, onClose]);

  const refresh = actions.refresh;
  useEffect(() => {
    if (!finished) return;
    toast.success(t("connected", { name }));
    void refresh();
    onClose();
  }, [finished, refresh, onClose, t, name]);

  const close = () => {
    // Best effort: an abandoned sign-in also expires on its own at the provider.
    if (started !== null && !finished)
      void actions.cancel.mutateAsync(started.state).catch(() => {});
    onClose();
  };

  const submit = (signIn: SubscriptionSignIn) => async (event: FormEvent) => {
    event.preventDefault();
    try {
      await actions.complete.mutateAsync({ state: signIn.state, redirectUrl: redirectUrl.trim() });
      void status.refetch();
    } catch (error) {
      toast.error(getErrorMessage(error, errors));
    }
  };

  const device = started?.user_code != null;
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("dialogTitle", { name })}</DialogTitle>
          <DialogDescription>
            {device ? t("deviceHelp") : t("browserHelp")}
            <span className="mt-2 block">{t("risk")}</span>
          </DialogDescription>
        </DialogHeader>

        {started === null ? (
          <p className="text-muted-foreground text-sm" aria-live="polite">
            {t("starting")}
          </p>
        ) : (
          <form id={formId} onSubmit={submit(started)} className="space-y-4" aria-live="polite">
            {device && (
              <div className="flex flex-wrap items-center gap-3">
                <code className="bg-muted rounded-md px-3 py-1.5 font-mono text-lg tracking-[0.2em] tabular-nums">
                  {started.user_code}
                </code>
                <IconButton
                  type="button"
                  variant="ghost"
                  aria-label={t("copyCode")}
                  onClick={() => {
                    void navigator.clipboard?.writeText(started.user_code ?? "");
                    setCopied(true);
                  }}
                >
                  {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                </IconButton>
              </div>
            )}
            <Button asChild variant="outline" size="sm">
              <a href={started.url} target="_blank" rel="noreferrer noopener">
                <ExternalLink aria-hidden />
                {t("openSignIn", { name })}
              </a>
            </Button>
            {!device && (
              <div className="space-y-2">
                <p className="text-muted-foreground text-xs">{t("localReturnHelp")}</p>
                <FormField htmlFor={`${formId}-redirect`} label={t("redirectLabel")}>
                  <Input
                    id={`${formId}-redirect`}
                    value={redirectUrl}
                    onChange={(event) => setRedirectUrl(event.target.value)}
                    placeholder="http://localhost:…"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </FormField>
              </div>
            )}
            <p className={refused ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
              {refused ? (status.data?.error ?? t("refused")) : t("waiting")}
            </p>
          </form>
        )}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={close}>
            {common("cancel")}
          </Button>
          {started !== null && !device && (
            <Button
              type="submit"
              form={formId}
              disabled={redirectUrl.trim() === "" || actions.complete.isPending}
            >
              {t("finish")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
