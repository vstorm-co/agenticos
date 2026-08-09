"use client";

import { useEffect, useState } from "react";
import { MessageSquare, Unlink } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { SectionCard } from "@/components/settings/settings-section";
import { listLinkedAccounts, unlinkAccount, type ChannelIdentity } from "@/lib/channel-link-api";
import { getErrorMessage } from "@/lib/utils";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<string, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
};

/**
 * The chat accounts this person has connected, and how to disconnect one.
 *
 * A link is granted in a chat and spent on a confirmation page, so without this
 * the only record of what somebody connected is a message that scrolled away -
 * and there was no way to undo it at all. It belongs on the profile rather than
 * with the organization's channels because these rows are *personal*: a run
 * started from one spends this person's budget and carries their permissions.
 */
export function ChatAccounts() {
  const t = useTranslations("pages.settings");
  const [accounts, setAccounts] = useState<ChannelIdentity[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listLinkedAccounts()
      .then((found) => {
        if (!cancelled) setAccounts(found);
      })
      .catch((cause) => {
        if (!cancelled) {
          setAccounts([]);
          toast.error(getErrorMessage(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function disconnect(identity: ChannelIdentity) {
    setBusy(identity.id);
    try {
      await unlinkAccount(identity.id);
      setAccounts((current) => (current ?? []).filter((row) => row.id !== identity.id));
    } catch (cause) {
      toast.error(getErrorMessage(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <SectionCard title={t("chatAccounts")} description={t("chatAccountsDescription")}>
      {accounts !== null && accounts.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("noChatAccountsYet")}</p>
      )}
      <div className="space-y-2">
        {(accounts ?? []).map((account) => (
          <div key={account.id} className="space-y-3 rounded-lg border p-3">
            <div className="flex items-center gap-3">
              <div className="bg-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <MessageSquare className="text-muted-foreground h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {account.platform_display_name ?? account.platform_username ?? account.id}
                </p>
                <p className="text-muted-foreground text-xs">
                  {PLATFORM_LABEL[account.platform] ?? account.platform}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy === account.id}
                aria-label={t("disconnectAccount", {
                  account: account.platform_username ?? account.platform,
                })}
                onClick={() => void disconnect(account)}
              >
                <Unlink className="h-4 w-4" />
              </Button>
            </div>

            {/* Which server, and what answers there. "Mattermost" alone does
                not say which company's chat this is on a deployment with two
                of them, and the agents are the reason somebody connected the
                account in the first place. */}
            {account.places.length === 0 ? (
              <p className="text-muted-foreground text-xs">{t("chatAccountNotUsedYet")}</p>
            ) : (
              account.places.map((place) => (
                <div key={place.bot_id} className="border-l pl-3 text-xs">
                  <p className="truncate">
                    {place.host ? `${place.bot_name} · ${place.host}` : place.bot_name}
                  </p>
                  {place.agents.length === 0 ? (
                    <p className="text-muted-foreground">{t("chatAccountNoAgentsHere")}</p>
                  ) : (
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <span className="text-muted-foreground">{t("chatAccountAnswersAs")}</span>
                      {place.agents.map((agent) => (
                        <span key={agent.id} className="flex items-center gap-1.5">
                          <AgentAvatar
                            agentId={agent.id}
                            name={agent.name}
                            hasAvatar={agent.has_avatar}
                            size="sm"
                          />
                          <span className="truncate">@{agent.slug}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
