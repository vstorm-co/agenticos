"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { BrandIcon } from "@/components/icons/brand-icon";
import { Badge, Button } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SectionCard } from "@/components/settings/settings-section";
import { LocalAgentSettings } from "@/components/desktop/local-agent-settings";
import { useCodingAccounts } from "@/hooks/use-coding-accounts";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { getErrorMessage } from "@/lib/api-error";
import type { CodingHarness } from "@/lib/coding-accounts-api";
import { CodingAccountConnect } from "./coding-account-connect";

const HARNESSES: readonly CodingHarness[] = ["claude_code", "codex"];

/** Every coding account a person may connect, in their settings. */
export function CodingAccounts() {
  const t = useTranslations("codingAccounts");
  const shell = useShell();
  return (
    <>
      <SectionCard
        title={t("title")}
        description={t("description")}
        tour="personal-coding-accounts"
      >
        <CodingAccountList harnesses={HARNESSES} />
        <p className="text-muted-foreground mt-3 text-xs leading-relaxed">{t("localHelp")}</p>
        <p className="text-muted-foreground mt-2 text-xs">{t("disconnectHelp")}</p>
      </SectionCard>
      {isDesktopShell(shell) && <LocalAgentSettings />}
    </>
  );
}

/**
 * The one account a chat's agent needs: its coding agent runs as a private cloud
 * task on the person's own account, so the chat offers to connect that account and
 * no other.
 */
export function PersonalCodingAccount({ harness }: { harness: CodingHarness }) {
  const t = useTranslations("codingAccounts");
  return (
    <section
      aria-label={t("chatTitle", { name: t(harness) })}
      className="border-foreground/10 rounded-xl border p-3"
      data-tour="chat-coding-accounts"
    >
      <h3 className="text-[13px] font-medium">{t("chatTitle", { name: t(harness) })}</h3>
      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{t("chatHelp")}</p>
      <CodingAccountList harnesses={[harness]} />
    </section>
  );
}

function CodingAccountList({ harnesses }: { harnesses: readonly CodingHarness[] }) {
  const t = useTranslations("codingAccounts");
  const errors = useTranslations("errors");
  const actions = useCodingAccounts();
  const [connecting, setConnecting] = useState<CodingHarness | null>(null);
  const rows = actions.accounts.data?.items ?? [];
  const failure = (error: unknown) => toast.error(getErrorMessage(error, errors));
  if (actions.accounts.error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void actions.accounts.refetch() }}
      />
    );
  return (
    <>
      <ul className="divide-border divide-y">
        {harnesses.map((harness) => {
          const account = rows.find((item) => item.harness === harness);
          return (
            <li key={harness} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="bg-muted grid size-9 shrink-0 place-items-center rounded-lg">
                  <BrandIcon name={harness} className="size-5" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t(harness)}</p>
                  <p className="text-muted-foreground text-xs">
                    {account?.label ?? t("notConnected")}
                  </p>
                  {account && (
                    <Badge variant="outline" className="mt-1">
                      {account.enabled ? t("enabled") : t("disabled")}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {account ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actions.consent.isPending}
                      onClick={() => void actions.consent.mutateAsync(account).catch(failure)}
                    >
                      {account.enabled ? t("disable") : t("enable")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actions.disconnect.isPending}
                      onClick={() => void actions.disconnect.mutateAsync(account.id).catch(failure)}
                    >
                      {t("disconnect")}
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!actions.ready || actions.accounts.isLoading}
                    onClick={() => setConnecting(harness)}
                  >
                    {t("connect")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {connecting && (
        <CodingAccountConnect
          key={actions.scope}
          harness={connecting}
          actions={actions}
          onClose={() => setConnecting(null)}
        />
      )}
    </>
  );
}
