"use client";

import { useState } from "react";
import { Brain, Loader2, Newspaper, Wallet } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ServiceCard } from "@/components/settings/service-card";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { ErrorState } from "@/components/states";
import { Badge, Button, Input, Skeleton, Switch } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useModelProviders, useOrganizations, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useTenantId } from "@/hooks/use-organizations";
import { useSystemAgents } from "@/hooks/use-system-agents";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import type { SystemAgent } from "@/lib/system-agents-api";
import type { Organization } from "@/types";
import { Perm } from "@/types/permissions";

const MODEL_FIELD = "model_profile_id";
const BUDGET_FIELD = "monthly_budget_usd";

/**
 * The platform's own background roles: what each runs on, what it has spent this
 * month and what it has done lately.
 *
 * Roles are not agents. Nothing here has instructions a person wrote, so nothing
 * is attributed to the starter agent or anyone else whose instructions did not
 * run; each execution is listed under the role that did it. The daily briefing is
 * edited here through the organization setting, so it shares its model and limit
 * with suggestions. Memory maintenance has its own model and budget.
 */
export function OrgSystemAgents({
  org,
  excludeBriefing = false,
}: {
  org: Organization;
  excludeBriefing?: boolean;
}) {
  const { can } = usePermissions();
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const tenantId = useTenantId();
  // The roles are the active organization's: this page can be opened for another one the
  // person belongs to, and showing - or changing - the active organization's model and
  // budget under that other name would be a settings page lying about whose it is.
  const allowed = can(Perm.budgetsManage) && tenantId === org.id;
  const { roles, isLoading, error, refresh } = useSystemAgents(allowed);
  if (!allowed) return null;
  if (isLoading) return <RolesLoading />;
  // Said, not hidden: an operator must not read a failed request as a product with no
  // system-agent settings.
  if (error || !roles)
    return (
      <ErrorState
        description={error ? getErrorMessage(error, tErrors) : undefined}
        cta={{ label: tc("retry"), onClick: () => void refresh() }}
      />
    );
  return (
    <div className="grid items-stretch gap-3" data-tour="org-system-agents">
      {roles
        .filter((role) => !excludeBriefing || role.role !== "daily_briefing")
        .map((role) => (
          <Role key={role.role} agent={role} org={org} />
        ))}
    </div>
  );
}

function RolesLoading() {
  const states = useTranslations("states");
  return (
    <div role="status" aria-label={states("loading")} aria-busy="true" className="grid gap-3">
      {[0, 1].map((item) => (
        <div key={item} aria-hidden className="bg-background overflow-hidden rounded-xl border">
          <div className="flex items-center gap-3 p-4">
            <Skeleton className="size-9 shrink-0 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-3 w-48" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Role({ agent, org }: { agent: SystemAgent; org: Organization }) {
  return <Profile agent={agent} org={org} />;
}

function Profile({ agent, org }: { agent: SystemAgent; org: Organization }) {
  const t = useTranslations("teams.systemAgents");
  const tErrors = useTranslations("errors");
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const { update, refresh } = useSystemAgents(true);
  const { setProactivity } = useOrganizations();
  const proactive = useTranslations("teams.proactive");
  const briefing = agent.role === "daily_briefing";
  const [open, setOpen] = useState(false);
  const modelId = briefing ? (org.proactive_model_profile_id ?? null) : agent.model_profile_id;
  const budget = briefing ? (org.proactive_limit_usd ?? "1") : agent.monthly_budget_usd;
  const saved = {
    enabled: Boolean((briefing ? org.proactive_enabled : agent.enabled) && modelId),
    modelId,
    budget: budget === null ? "" : String(Number(budget)),
  };
  const [form, setForm] = useState(saved);
  const [pending, setPending] = useState(0);
  const [saving, setSaving] = useState(false);
  const busy = saving || update.isPending;
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (useChanged(JSON.stringify(saved))) setForm(saved);
  const changed = JSON.stringify(form) !== JSON.stringify(saved);
  const edit = (next: Partial<typeof form>) => {
    setForm((current) => ({ ...current, ...next }));
    setErrors({});
  };

  const save = async () => {
    const budget = form.budget.trim();
    if (
      (briefing && budget === "") ||
      (budget !== "" && (!Number.isFinite(Number(budget)) || Number(budget) < 0))
    ) {
      setErrors({ [BUDGET_FIELD]: t("invalid") });
      return;
    }
    if (form.enabled && form.modelId === null) {
      setErrors({ [MODEL_FIELD]: t("modelRequired") });
      return;
    }
    setSaving(true);
    try {
      if (briefing) {
        await setProactivity(org.id, {
          proactive_enabled: form.enabled,
          proactive_model_profile_id: form.modelId,
          proactive_limit_usd: Number(budget),
        });
        await refresh();
      } else
        await update.mutateAsync({
          role: agent.role,
          change: {
            enabled: form.enabled,
            model_profile_id: form.modelId,
            monthly_budget_usd: budget === "" ? null : budget,
          },
        });
      toast.success(form.enabled ? t("saved") : t("savedOff"));
    } catch (failure) {
      const modelField = briefing ? "proactive_model_profile_id" : MODEL_FIELD;
      const budgetField = briefing ? "proactive_limit_usd" : BUDGET_FIELD;
      const problem = submitFailure(failure, { fields: [modelField, budgetField] }, tErrors);
      setErrors({
        ...(problem.fields[modelField] ? { [MODEL_FIELD]: problem.fields[modelField] } : {}),
        ...(problem.fields[budgetField] ? { [BUDGET_FIELD]: problem.fields[budgetField] } : {}),
      });
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <ServiceCard
      title={t(`roles.${agent.role}.name`)}
      description={t("configure")}
      icon={briefing ? Newspaper : Brain}
      collapsible
      open={open}
      onOpenChange={setOpen}
      id={`system-agent-${agent.role}-settings`}
      testId={`system-agent-${agent.role}`}
      status={
        <Badge variant={form.enabled ? "success" : "secondary"}>
          {form.enabled ? t("on") : t("off")}
        </Badge>
      }
      action={
        <Switch
          id={`system-agent-${agent.role}-enabled`}
          aria-label={t("enabled")}
          checked={form.enabled}
          disabled={busy || form.modelId === null}
          onCheckedChange={(enabled) => {
            edit({ enabled });
            setOpen(true);
          }}
        />
      }
    >
      <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
        {t(`roles.${agent.role}.what`)}
      </p>
      {agent.unavailable && (
        <p role="status" className="text-destructive text-sm">
          {t("starterAgentMissing")}
        </p>
      )}
      <fieldset className="min-w-0 space-y-2" disabled={busy}>
        <legend className="text-sm font-medium">{t("model")}</legend>
        <ModelProfilePicker
          profiles={profiles}
          generationSettings
          profilesStatus={profilesStatus}
          value={form.modelId}
          onChange={(modelId) => edit({ modelId, ...(modelId === null ? { enabled: false } : {}) })}
          onCreationPendingChange={(creating) => setPending((count) => count + (creating ? 1 : -1))}
          allowAdd={can(Perm.connectionsManage)}
          disabled={busy}
        />
        {errors[MODEL_FIELD] ? (
          <p className="text-destructive text-xs">{errors[MODEL_FIELD]}</p>
        ) : (
          <p className="text-muted-foreground text-xs">{t("modelHint")}</p>
        )}
      </fieldset>
      <FormField
        label={briefing ? proactive("label") : t("budget")}
        htmlFor={`system-agent-${agent.role}-budget`}
        error={errors[BUDGET_FIELD] ?? null}
      >
        <Input
          id={`system-agent-${agent.role}-budget`}
          type="number"
          min="0"
          step="0.5"
          placeholder={t("noBudget")}
          value={form.budget}
          disabled={busy}
          onChange={(event) => edit({ budget: event.target.value })}
        />
      </FormField>
      <Button onClick={save} disabled={!changed || busy || pending > 0}>
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {t("save")}
      </Button>
      <SystemAgentActivity agent={agent} />
    </ServiceCard>
  );
}

export function SystemAgentActivity({ agent }: { agent: SystemAgent }) {
  return (
    <div className="space-y-3 border-t pt-4">
      <Spend agent={agent} />
      <History agent={agent} />
    </div>
  );
}

function Spend({ agent }: { agent: SystemAgent }) {
  const t = useTranslations("teams.systemAgents");
  const format = useFormatter();
  const spent = Number(agent.spent_this_month);
  const money = (value: number) =>
    format.number(value, { style: "currency", currency: "USD", maximumFractionDigits: 4 });
  return (
    <p className="text-foreground flex items-center gap-2 text-sm font-medium tabular-nums">
      <Wallet className="text-muted-foreground size-4 shrink-0" aria-hidden />
      {agent.monthly_budget_usd === null
        ? t("spent", { amount: money(spent) })
        : t("spentOf", { amount: money(spent), budget: money(Number(agent.monthly_budget_usd)) })}
    </p>
  );
}

function History({ agent }: { agent: SystemAgent }) {
  const t = useTranslations("teams.systemAgents");
  const format = useFormatter();
  if (agent.runs.length === 0) {
    return <p className="text-muted-foreground text-xs">{t("noRuns")}</p>;
  }
  return (
    <ul className="divide-foreground/10 divide-y rounded-md border text-xs">
      {agent.runs.map((run) => (
        <li key={run.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
          <span>
            {format.dateTime(new Date(run.started_at), { dateStyle: "medium", timeStyle: "short" })}
          </span>
          <span className="text-muted-foreground">{run.model_label ?? t("unknownModel")}</span>
          <span>
            {format.number(Number(run.cost_usd), {
              style: "currency",
              currency: "USD",
              maximumFractionDigits: 4,
            })}
          </span>
          <Badge variant={run.status === "completed" ? "outline" : "destructive"}>
            {run.status}
          </Badge>
          {run.error ? <span className="text-destructive basis-full">{run.error}</span> : null}
        </li>
      ))}
    </ul>
  );
}
