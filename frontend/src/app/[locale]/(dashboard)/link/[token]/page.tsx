"use client";

import { use, useEffect, useState } from "react";
import { Check, Link2, MessageSquare } from "lucide-react";

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
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
 * Reached from a URL a bot sent, and inside the dashboard on purpose: the token
 * says which chat account is on offer and the session says who is accepting, and
 * only the second of those can be trusted - the first arrived in a chat.
 *
 * Which account is named before anything is joined. A page that says only
 * "connect your account" asks somebody to trust a URL, and this is a URL that
 * arrived in a chat.
 */
export default function ChannelLinkPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const t = useTranslations("pages.channelLink");
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
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function confirm() {
    setConfirming(true);
    try {
      await confirmChannelLink(token);
      setLinked(true);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setConfirming(false);
    }
  }

  const account =
    request === null
      ? ""
      : (request.platform_username ?? request.platform_display_name ?? t("thatAccount"));

  return (
    <div className="mx-auto max-w-lg py-12">
      <Card>
        <CardHeader>
          <div className="bg-muted text-muted-foreground mb-3 flex h-11 w-11 items-center justify-center rounded-xl">
            {linked ? <Check className="h-5 w-5" /> : <Link2 className="h-5 w-5" />}
          </div>
          <CardTitle>{linked ? t("connected") : t("connectYourChatAccount")}</CardTitle>
          <CardDescription>
            {linked ? t("goBackToTheChat") : t("theAgentWillRunAsYou")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* A dead link and a page that failed to load are the same pixels
              otherwise, and only one of them is worth trying again. */}
          {error !== null && <p className="text-destructive text-sm">{error}</p>}

          {request !== null && !linked && (
            <>
              <div className="flex items-center gap-3 rounded-md border p-3">
                <MessageSquare className="text-muted-foreground h-4 w-4 shrink-0" />
                <div className="min-w-0">
                  <p className="truncate text-sm">{account}</p>
                  <p className="text-muted-foreground text-xs">
                    {PLATFORM_LABEL[request.platform] ?? request.platform}
                  </p>
                </div>
              </div>
              <Button onClick={confirm} disabled={confirming} className="w-full">
                {t("connectThisAccount")}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
