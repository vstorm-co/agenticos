"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useAuthStore } from "@/stores";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import {
  startCopilotSignIn,
  pollCopilotSignIn,
  type PersonalModelDestination,
  type CopilotSignInChallenge,
} from "@/lib/personal-model-keys-api";

export function CopilotModelConnection({
  agentId,
  destination,
  connected,
}: {
  agentId: string;
  destination: PersonalModelDestination;
  connected: boolean;
}) {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  if (!tenant || !user) return null;
  // Remount the flow on identity/destination changes. Late results belong to
  // the previous component and can never display its code in the new scope.
  return (
    <CopilotFlow
      key={`${tenant}:${user}:${agentId}:${JSON.stringify(destination)}`}
      agentId={agentId}
      tenant={tenant}
      user={user}
      destination={destination}
      connected={connected}
    />
  );
}

function CopilotFlow({
  agentId,
  destination,
  connected,
  tenant,
  user,
}: {
  agentId: string;
  destination: PersonalModelDestination;
  connected: boolean;
  tenant: string;
  user: string;
}) {
  const t = useTranslations("personalModelKeys.copilot");
  const errors = useTranslations("errors");
  const guard = useTenantGuard();
  const client = useQueryClient();
  const [challenge, setChallenge] = useState<CopilotSignInChallenge | null>(null);
  const [wait, setWait] = useState<number | null>(null);
  const active = () => guard(tenant) && useAuthStore.getState().user?.id === user;
  const start = useMutation({
    mutationFn: () => startCopilotSignIn(agentId, destination),
    onSuccess: (result) => {
      if (!active()) return;
      setChallenge(result);
      setWait(null);
    },
  });
  const poll = useMutation({
    mutationFn: (handle: string) => pollCopilotSignIn(agentId, handle),
    onSuccess: (result) => {
      if (!active()) return;
      if (result.status === "connected") {
        setChallenge(null);
        void client.invalidateQueries({
          queryKey: qk.personalModelKeys.all(`${tenant}:${user}`),
        });
      } else setWait(result.poll_after_seconds);
    },
  });
  const error = start.error ?? poll.error;
  return (
    <div className="space-y-3 p-3" role="region" aria-label={t("title")}>
      <p className="text-sm font-medium">{t("title")}</p>
      <p className="text-muted-foreground text-xs">
        {t("destination", { model: destination.model })}
      </p>
      <p className="text-muted-foreground text-xs">{t("privacy")}</p>
      {connected && <p className="text-muted-foreground text-xs">{t("retained")}</p>}
      {challenge && (
        <div className="space-y-2">
          <p className="text-sm">{t("approveOwnCode")}</p>
          <p className="font-mono text-lg" aria-label={t("code")}>
            {challenge.user_code}
          </p>
          <a
            href={challenge.verification_uri}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary text-sm underline"
          >
            {t("openGitHub")}
          </a>
          {wait !== null && (
            <p role="status" className="text-muted-foreground text-xs">
              {t("pending", { seconds: wait })}
            </p>
          )}
          <div>
            <Button
              type="button"
              size="sm"
              disabled={poll.isPending || start.isPending}
              onClick={() => poll.mutate(challenge.handle)}
            >
              {t("check")}
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {getErrorMessage(error, errors)}
        </p>
      )}
      <Button
        type="button"
        size="sm"
        disabled={start.isPending || poll.isPending}
        onClick={() => {
          poll.reset();
          setChallenge(null);
          setWait(null);
          start.mutate();
        }}
      >
        {t(challenge ? "restart" : connected ? "reconnect" : "connect")}
      </Button>
    </div>
  );
}
