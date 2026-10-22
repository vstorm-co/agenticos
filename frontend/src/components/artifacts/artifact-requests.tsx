"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { Badge, Button, Label, Switch } from "@/components/ui";
import {
  isConsentRequired,
  useArtifactRequestActions,
  useArtifactRequests,
} from "@/hooks/use-artifact-requests";
import type { ArtifactDetail, ArtifactShareRequest } from "@/types/artifact";

interface ArtifactRequestsProps {
  artifact: ArtifactDetail;
  /** Opens the review of a version request. */
  onReview: (request: ArtifactShareRequest) => void;
  /** Approving failed for want of consent on the page's data: the caller offers Confirm data. */
  onConsentRequired: () => void;
}

/** Who a request is from, or a stand-in for a person the server could not name. */
function requesterName(request: ArtifactShareRequest, fallback: string): string {
  return request.requester_name ?? fallback;
}

/** What an `audience` request asks for, in words. */
function AudienceAsk({ request }: { request: ArtifactShareRequest }) {
  const t = useTranslations("artifacts.requests");
  const parts = [
    ...(request.requested_visibility === null
      ? []
      : [t("askVisibility", { visibility: request.requested_visibility })]),
    ...request.requested_subjects.map((subject) =>
      t("askSubject", {
        who: subject.email ?? subject.group_name ?? "",
        level: subject.level,
      }),
    ),
  ];
  return <p className="text-muted-foreground text-sm">{parts.join("; ")}</p>;
}

function RequestRow({
  request,
  busy,
  onApprove,
  onDecline,
  onReview,
}: {
  request: ArtifactShareRequest;
  busy: boolean;
  onApprove: () => void;
  onDecline: () => void;
  onReview: () => void;
}) {
  const t = useTranslations("artifacts.requests");
  const format = useFormatter();
  const name = requesterName(request, t("someone"));
  return (
    <li className="space-y-1.5 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {t("kind", { kind: request.kind, name, version: request.version_number ?? 0 })}
        </p>
        {request.status !== "pending" && (
          <Badge variant="outline">
            {t("state", { status: request.status, reason: request.void_reason ?? "none" })}
          </Badge>
        )}
      </div>
      {request.kind === "audience" && <AudienceAsk request={request} />}
      {request.note !== null && (
        <p className="text-muted-foreground text-sm">{t("note", { note: request.note })}</p>
      )}
      <p className="text-muted-foreground text-xs">
        {format.dateTime(new Date(request.created_at), { dateStyle: "medium", timeStyle: "short" })}
      </p>
      {request.can_decide && (
        <div className="flex flex-wrap gap-2 pt-1">
          {request.kind === "version" ? (
            // Approving a version confirms its data, which is decided only from the review.
            <Button size="sm" onClick={onReview}>
              {t("review")}
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={busy}
              aria-label={t("approveFrom", { name })}
              onClick={onApprove}
            >
              {t("approve")}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            aria-label={t("declineFrom", { name })}
            onClick={onDecline}
          >
            {t("decline")}
          </Button>
        </div>
      )}
    </li>
  );
}

/**
 * The requests about one page: the ones waiting first, each worded by what it asks.
 *
 * Whoever may decide a request is offered Approve and Decline on it (the server's
 * `can_decide`); everyone else sees their own. A stale answer (409) reads the list
 * again through the hook. Approving where the page's data lacks consent is not
 * refused silently: the caller is told, to say so and offer Confirm data.
 */
export function ArtifactRequests({ artifact, onReview, onConsentRequired }: ArtifactRequestsProps) {
  const t = useTranslations("artifacts.requests");
  const [includeDecided, setIncludeDecided] = useState(false);
  const { requests, isLoading } = useArtifactRequests(artifact.id, includeDecided, true);
  const { approve, decline } = useArtifactRequestActions(artifact.id);
  const decider = artifact.can_edit || artifact.may_change_owner;

  if (!decider && requests.length === 0) return null;

  const busy = approve.isPending || decline.isPending;
  return (
    <section className="space-y-3" aria-labelledby="artifact-requests-title">
      <div className="flex items-center justify-between gap-3">
        <h3 id="artifact-requests-title" className="text-sm font-semibold">
          {t("title")}
        </h3>
        {decider && (
          <div className="flex items-center gap-2">
            <Switch
              id="artifact-requests-decided"
              checked={includeDecided}
              onCheckedChange={setIncludeDecided}
            />
            <Label htmlFor="artifact-requests-decided" className="text-xs">
              {t("includeDecided")}
            </Label>
          </div>
        )}
      </div>
      {requests.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      )}
      <ul className="space-y-2">
        {requests.map((request) => (
          <RequestRow
            key={request.id}
            request={request}
            busy={busy}
            onApprove={() =>
              approve.mutate(request.id, {
                onError: (error) => {
                  if (isConsentRequired(error)) onConsentRequired();
                },
              })
            }
            onDecline={() => decline.mutate(request.id)}
            onReview={() => onReview(request)}
          />
        ))}
      </ul>
    </section>
  );
}
