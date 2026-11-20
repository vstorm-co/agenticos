"use client";

import { useState } from "react";
import { ShieldCheck, TimerOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ScopePicker, useScopeChoice } from "@/components/settings/scope-picker";
import { EmptyState, LoadingState } from "@/components/states";
import {
  Button,
  Checkbox,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useConsentRequest, useOrganizations } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { OAuthConsentChoice, OAuthConsentRequest } from "@/types/mcp-oauth";

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
    return <LoadingState variant="pending" />;
  }
  if (request === null || error) {
    return <EmptyState icon={TimerOff} title={t("expiredTitle")} description={t("expiredWhy")} />;
  }
  return (
    <ConsentForm
      request={request}
      onApprove={(choice) => approve.mutateAsync(choice)}
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
  onApprove: (choice: OAuthConsentChoice) => Promise<{ redirect_to: string }>;
  onDeny: () => Promise<{ redirect_to: string }>;
  busy: boolean;
}) {
  const t = useTranslations("mcpOauth");
  const tErrors = useTranslations("errors");
  const { orgs, switchOrg } = useOrganizations();
  const choice = useScopeChoice(request.catalog);
  const [deploymentAdmin, setDeploymentAdmin] = useState(false);
  const allowDeployment = request.deployment_admin_available === true && deploymentAdmin;

  const answer = async (send: () => Promise<{ redirect_to: string }>) => {
    if (!busy) {
      try {
        leave((await send()).redirect_to);
      } catch (failure) {
        toast.error(getErrorMessage(failure, tErrors));
      }
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
        <Select value={request.organization_id} onValueChange={switchOrg} disabled={busy}>
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
      <ScopePicker catalog={request.catalog} choice={choice} id="consent-access" disabled={busy} />
      {request.deployment_admin_available && (
        <div className="border-border space-y-2 rounded-lg border p-4">
          <div className="flex items-center gap-2">
            <Checkbox
              id="deployment-admin"
              checked={allowDeployment}
              disabled={busy}
              aria-describedby="deployment-admin-hint"
              onCheckedChange={(checked) => setDeploymentAdmin(checked === true)}
            />
            <Label htmlFor="deployment-admin">{t("deploymentAdminTitle")}</Label>
          </div>
          <p id="deployment-admin-hint" className="text-muted-foreground text-xs">
            {t("deploymentAdminHint")}
          </p>
        </div>
      )}
      <p className="text-muted-foreground text-xs">{t("revokeLater")}</p>
      <div className="flex justify-end gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void answer(onDeny)}>
          {t("deny")}
        </Button>
        <Button
          disabled={busy || (choice.scopes.length === 0 && !allowDeployment)}
          onClick={() =>
            void answer(() =>
              onApprove({
                scopes: choice.scopes,
                ...(allowDeployment ? { deployment_admin: true } : {}),
              }),
            )
          }
        >
          {t("allow")}
        </Button>
      </div>
    </div>
  );
}
