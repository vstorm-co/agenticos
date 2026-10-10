"use client";

import { ShieldCheck, TimerOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ScopePicker, useScopeChoice } from "@/components/settings/scope-picker";
import { EmptyState, LoadingState } from "@/components/states";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useConsentRequest, useOrganizations } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { OAuthConsentRequest } from "@/types/mcp-oauth";

/** Send the browser back to the client. A full navigation: it leaves the console. */
function leave(to: string) {
  window.location.assign(to);
}

/**
 * The page an MCP client sends a person to, to let it act as them (#2059).
 *
 * It says who is asking and where the answer goes back to, lets the person pick
 * the organization and what the application may do there, and hands the answer
 * to the client. Nothing here grants more than the person holds.
 */
export function ConsentScreen({ requestId }: { requestId: string }) {
  const t = useTranslations("mcpOauth");
  const { request, isLoading, error, approve, deny } = useConsentRequest(requestId);

  if (isLoading) {
    return <LoadingState variant="skeleton-panel" rows={4} />;
  }
  if (request === null || error) {
    return <EmptyState icon={TimerOff} title={t("expiredTitle")} description={t("expiredWhy")} />;
  }
  return (
    <ConsentForm
      request={request}
      onApprove={(scopes) => approve.mutateAsync(scopes)}
      onDeny={() => deny.mutateAsync()}
      busy={approve.isPending || deny.isPending}
    />
  );
}

function ConsentForm({
  request,
  onApprove,
  onDeny,
  busy,
}: {
  request: OAuthConsentRequest;
  onApprove: (scopes: OAuthConsentRequest["catalog"]["scopes"]) => Promise<{ redirect_to: string }>;
  onDeny: () => Promise<{ redirect_to: string }>;
  busy: boolean;
}) {
  const t = useTranslations("mcpOauth");
  const tErrors = useTranslations("errors");
  const { orgs, switchOrg } = useOrganizations();
  const choice = useScopeChoice(request.catalog);

  const answer = async (send: () => Promise<{ redirect_to: string }>) => {
    try {
      leave((await send()).redirect_to);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };

  return (
    <div className="border-border bg-card mx-auto w-full max-w-lg space-y-6 rounded-xl border p-6">
      <div className="flex items-start gap-3">
        <ShieldCheck className="text-muted-foreground mt-0.5 h-5 w-5 shrink-0" />
        <div className="space-y-1">
          <h1 className="text-foreground text-lg font-semibold">
            {t("title", { client: request.client_name })}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t("why", { host: request.redirect_host })}
          </p>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="consent-organization">{t("organization")}</Label>
        <Select value={request.organization_id} onValueChange={switchOrg}>
          <SelectTrigger id="consent-organization">
            <SelectValue>{request.organization_name}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {orgs.map((org) => (
              <SelectItem key={org.id} value={org.id}>
                {org.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ScopePicker catalog={request.catalog} choice={choice} id="consent-access" />
      <p className="text-muted-foreground text-xs">{t("revokeLater")}</p>
      <div className="flex justify-end gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void answer(onDeny)}>
          {t("deny")}
        </Button>
        <Button
          disabled={busy || choice.scopes.length === 0}
          onClick={() => void answer(() => onApprove(choice.scopes))}
        >
          {t("allow")}
        </Button>
      </div>
    </div>
  );
}
