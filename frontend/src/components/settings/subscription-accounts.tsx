"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Check, Copy, ExternalLink, MoreHorizontal } from "lucide-react";
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
  DataTable,
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  type Column,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SubscriptionAccountUsage } from "@/components/agents/subscription-account-usage";
import { SectionCard } from "@/components/settings/settings-section";
import { ProviderRow } from "@/components/vault/provider-row";
import { SearchInput } from "@/components/ui/list-controls";
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
  type SubscriptionAccount,
} from "@/lib/subscription-accounts-api";

interface SubscriptionRow {
  id: string;
  provider: SubscriptionProvider;
  account: SubscriptionAccount | null;
  name: string;
}

/** One account per row, using the same table and pagination as the vault. */
export function SubscriptionAccounts() {
  const t = useTranslations("subscriptionAccounts");
  const models = useTranslations("modelSources");
  const errors = useTranslations("errors");
  const actions = useSubscriptionAccounts();
  const [connecting, setConnecting] = useState<SubscriptionProvider | null>(null);
  const [query, setQuery] = useState("");
  const listed = actions.accounts.data;
  if (listed !== undefined && !listed.enabled) return null;
  const own = listed?.items ?? [];
  const providers = [...SUBSCRIPTION_PROVIDERS].sort(
    (a, b) =>
      Number(own.some((account) => subscriptionBelongsTo(account, b))) -
      Number(own.some((account) => subscriptionBelongsTo(account, a))),
  );
  const rows: SubscriptionRow[] = providers.flatMap<SubscriptionRow>((provider) => {
    const accounts = own.filter((account) => subscriptionBelongsTo(account, provider));
    return accounts.length
      ? accounts.map((account, index) => ({
          id: account.name,
          provider,
          account,
          name: account.email || account.label || models("accountNumber", { number: index + 1 }),
        }))
      : [{ id: `provider:${provider}`, provider, account: null, name: "" }];
  });
  const needle = query.trim().toLocaleLowerCase();
  const filtered = rows.filter((row) =>
    `${t(`providers.${row.provider}`)} ${row.name}`.toLocaleLowerCase().includes(needle),
  );
  const failure = (error: unknown) => toast.error(getErrorMessage(error, errors));
  const columns: Column<SubscriptionRow>[] = [
    {
      key: "provider",
      header: t("tableProvider"),
      sortable: true,
      sortValue: (row) => t(`providers.${row.provider}`),
      className: "w-[22%] min-w-40",
      cell: (row) => (
        <ProviderRow
          wrap
          provider={SUBSCRIPTION_MARK[row.provider]}
          name={t(`providers.${row.provider}`)}
        />
      ),
    },
    {
      key: "account",
      header: models("account"),
      sortable: true,
      sortValue: (row) => row.name,
      className: "w-[22%] max-w-64 @max-md/table:w-full @max-md/table:max-w-none",
      cell: (row) => (
        <span className="block text-xs [overflow-wrap:anywhere]" title={row.name}>
          {row.account ? row.name : t("noAccount")}
        </span>
      ),
    },
    {
      key: "status",
      header: t("tableStatus"),
      className: "w-28",
      cell: (row) => (
        <Badge
          variant={
            row.account && !row.account.disabled && !row.account.unavailable ? "success" : "outline"
          }
        >
          {row.account
            ? row.account.disabled || row.account.unavailable
              ? t("unavailable")
              : models("connected")
            : t("notConnected")}
        </Badge>
      ),
    },
    {
      key: "usage",
      header: models("usageAndLimits"),
      className: "min-w-64",
      cell: (row) =>
        row.account ? (
          <SubscriptionAccountUsage account={row.account} compact />
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        ),
    },
    {
      key: "actions",
      header: t("tableActions"),
      align: "right",
      className: "w-36",
      cell: (row) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="button"
            size="sm"
            variant={row.account ? "ghost" : "outline"}
            disabled={!actions.ready || actions.accounts.isLoading}
            onClick={() => setConnecting(row.provider)}
          >
            {row.account ? t("connectAnother") : t("connect")}
          </Button>
          {row.account && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" size="icon-sm" variant="ghost" aria-label={t("tableActions")}>
                  <MoreHorizontal aria-hidden className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={actions.disconnect.isPending}
                  onSelect={() => {
                    if (row.account)
                      void actions.disconnect.mutateAsync(row.account.name).catch(failure);
                  }}
                >
                  {t("disconnect")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      ),
    },
  ];
  return (
    <SectionCard
      title={t("title")}
      description={<p>{t("description")}</p>}
      tour="personal-subscription-accounts"
      className="flex min-h-0 flex-1 flex-col border-0"
      contentClassName="flex min-h-0 flex-1 flex-col gap-3 py-0"
    >
      <SearchInput value={query} onChange={setQuery} placeholder={t("search")} />
      <DataTable
        key={query}
        clientPagination
        pageSize={10}
        fillHeight
        stackOnNarrow
        columns={columns}
        rows={filtered}
        getRowKey={(row) => row.id}
        loading={actions.accounts.isLoading}
        error={
          actions.accounts.error ? (
            <ErrorState
              title={t("loadFailed")}
              cta={{ label: t("retry"), onClick: () => void actions.accounts.refetch() }}
            />
          ) : undefined
        }
        empty={<p className="text-muted-foreground p-5 text-sm">{t("noMatches")}</p>}
        className="rounded-none border-0 bg-transparent"
      />
      <p role="note" className="text-muted-foreground pb-4 text-xs">
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
  const pollFailed = status.isError;
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

  const device = started?.flow === "device" || started?.user_code != null;
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
            {device && started.user_code && (
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
            <p
              className={
                refused || pollFailed ? "text-destructive text-xs" : "text-muted-foreground text-xs"
              }
              role={pollFailed ? "alert" : undefined}
            >
              {pollFailed
                ? getErrorMessage(status.error, errors)
                : refused
                  ? (status.data?.error ?? t("refused"))
                  : t("waiting")}
            </p>
            {pollFailed && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={status.isFetching}
                onClick={() => void status.refetch()}
              >
                {common("retry")}
              </Button>
            )}
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
