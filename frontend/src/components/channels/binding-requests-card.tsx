"use client";

import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useChannelBindingRequests, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * Requests from agent publishers to put an agent in front of customers, or to change
 * how it is, on a public line - waiting for somebody with `channels:manage`.
 *
 * Renders nothing for anybody else and nothing when none wait, so the page stays what
 * it was. `?requests=open`, the link a notification and the dashboard row carry,
 * scrolls here.
 */
export function BindingRequestsCard() {
  const t = useTranslations("pages.channels");
  const { can } = usePermissions();
  const canManage = can(Perm.channelsManage);
  const { requests, approve, decline } = useChannelBindingRequests(canManage);
  const wanted = useSearchParams().get("requests") === "open";
  const card = useRef<HTMLDivElement>(null);
  const shown = canManage && requests.length > 0;

  useEffect(() => {
    if (wanted && shown) card.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [wanted, shown]);

  if (!shown) return null;

  return (
    <div ref={card} data-tour="channels-binding-requests" id="binding-requests">
      <Card>
        <CardHeader>
          <CardTitle>{t("bindingRequests")}</CardTitle>
          <CardDescription>{t("bindingRequestsHint")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {requests.map((request) => (
            <div
              key={request.id}
              className="flex flex-wrap items-center gap-3 rounded-md border p-3"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-sm">
                  {t("bindingRequestLine", {
                    kind: request.kind,
                    requester: request.requester_email ?? t("someone"),
                    agent: request.agent_name,
                    bot: request.channel_bot_name,
                  })}
                </p>
                {request.note && (
                  <p className="text-muted-foreground text-xs">
                    {t("bindingRequestNote", { note: request.note })}
                  </p>
                )}
              </div>
              <Button
                size="sm"
                disabled={approve.isPending || decline.isPending}
                onClick={() => approve.mutate(request.id)}
              >
                {t("approve")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={approve.isPending || decline.isPending}
                onClick={() => decline.mutate(request.id)}
              >
                {t("decline")}
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
