"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Link2, MessageSquare, ShieldCheck } from "lucide-react";

import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import {
  confirmChannelLink,
  readChannelLink,
  type ChannelLinkRequest,
} from "@/lib/channel-link-api";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<string, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
};

/**
 * Confirming that a chat account is yours.
 *
 * Reached from a URL a bot sent, and rendered inside the dashboard on purpose:
 * the token says which chat account is on offer and the session says who is
 * accepting, and only the second of those can be trusted - the first arrived in
 * a chat.
 *
 * Which account is named before anything is joined, and what confirming *means*
 * is said next to the button rather than left to be inferred. This page is the
 * one moment somebody is asked to attach their permissions and their budget to
 * an identity on another system, and the first version of it was a small card
 * floating in the corner of an empty page with four words on it.
 */
export default function ChannelLinkPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const t = useTranslations("pages.channelLink");
  const tErrors = useTranslations("errors");
  const [request, setRequest] = useState<ChannelLinkRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linked, setLinked] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    readChannelLink(token)
      .then((found) => {
        if (!cancelled) setRequest(found);
      })
      // Through `getErrorMessage`, so a code-only refusal from the proxy - the
      // 401 an expired cookie mints, among others - resolves against the
      // catalog instead of arriving humanized into English (#655).
      .catch((cause: unknown) => {
        if (!cancelled) setError(getErrorMessage(cause, tErrors));
      });
    return () => {
      cancelled = true;
    };
  }, [token, tErrors]);

  async function confirm() {
    setConfirming(true);
    try {
      await confirmChannelLink(token);
      setLinked(true);
    } catch (cause) {
      setError(getErrorMessage(cause, tErrors));
    } finally {
      setConfirming(false);
    }
  }

  const account =
    request === null
      ? ""
      : (request.platform_display_name ?? request.platform_username ?? t("thatAccount"));

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center">
      <div className="mb-8 text-center">
        <div
          className={`mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl ${
            linked ? "bg-emerald-500/10 text-emerald-600" : "bg-primary/10 text-primary"
          }`}
        >
          {linked ? <Check className="h-6 w-6" /> : <Link2 className="h-6 w-6" />}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {linked ? t("connected") : t("connectYourChatAccount")}
        </h1>
        <p className="text-muted-foreground mx-auto mt-2 max-w-sm text-sm">
          {linked ? t("goBackToTheChat") : t("theAgentWillRunAsYou")}
        </p>
      </div>

      {/* A dead link and a page that failed to load are the same pixels
          otherwise, and only one of them is worth trying again. */}
      {error !== null && (
        <Card className="border-destructive/40">
          <CardContent className="text-destructive p-5 text-sm">{error}</CardContent>
        </Card>
      )}

      {error === null && request === null && !linked && (
        <Card>
          <CardContent className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      )}

      {request !== null && !linked && (
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="bg-muted/40 flex items-center gap-3 rounded-lg border p-4">
              <div className="bg-background flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border">
                <MessageSquare className="text-muted-foreground h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{account}</p>
                <p className="text-muted-foreground text-xs">
                  {PLATFORM_LABEL[request.platform] ?? request.platform}
                </p>
              </div>
            </div>

            {/* What confirming actually does. Said here rather than in a
                tooltip: this is the moment somebody attaches their permissions
                and their spending to an account on another system. */}
            <ul className="text-muted-foreground space-y-2 text-sm">
              <li className="flex gap-2">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{t("runsWithYourPermissions")}</span>
              </li>
              <li className="flex gap-2">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{t("disconnectAnyTime")}</span>
              </li>
            </ul>

            <Button onClick={confirm} disabled={confirming} className="w-full" size="lg">
              {t("connectThisAccount")}
            </Button>
          </CardContent>
        </Card>
      )}

      {linked && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <p className="text-sm">{t("nowSaySomething")}</p>
            <Button asChild variant="outline" className="w-full">
              <Link href={ROUTES.SETTINGS_PROFILE}>
                {t("seeConnectedAccounts")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
