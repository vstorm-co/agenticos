"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { SettingsSection } from "@/components/settings/settings-section";
import { ErrorState } from "@/components/states";
import { Badge, Button, Input, Label, Switch } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useModelProviders, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useTenantId } from "@/hooks/use-organizations";
import { useSystemAgents } from "@/hooks/use-system-agents";
import { submitFailure } from "@/lib/api-error";
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
 * the proactivity setting above, shown with its history; memory maintenance is
 * configured here, on a model somebody chose and inside a budget of its own.
 */
export function OrgSystemAgents({ org }: { org: Organization }) {
  const t = useTranslations("teams.systemAgents");
  const { can } = usePermissions();
  const tenantId = useTenantId();
  // The roles are the active organization's: this page can be opened for another one the
  // person belongs to, and showing - or changing - the active organization's model and
  // budget under that other name would be a settings page lying about whose it is.
  const allowed = can(Perm.budgetsManage) && tenantId === org.id;
  const { roles, isLoading, error } = useSystemAgents(allowed);
  if (!allowed || isLoading) return null;
  // Said, not hidden: an operator must not read a failed request as a product with no
  // system-agent settings.
  if (error || !roles) return <ErrorState />;
  return (
    <SettingsSection title={t("title")} description={t("description")}>
      <div className="divide-foreground/10 space-y-6 divide-y [&>*:not(:first-child)]:pt-6">
        {roles.map((role) => (
          <Role key={role.role} agent={role} />
        ))}
      </div>
    </SettingsSection>
  );
}

function Role({ agent }: { agent: SystemAgent }) {
  const t = useTranslations("teams.systemAgents");
  return (
    <div className="space-y-4" data-testid={`system-agent-${agent.role}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-sm font-medium">{t(`roles.${agent.role}.name`)}</h3>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {t(`roles.${agent.role}.what`)}
          </p>
        </div>
        {agent.managed_in ? (
          <Badge variant="outline">{agent.enabled ? t("on") : t("off")}</Badge>
        ) : null}
      </div>
      {agent.unavailable ? (
        <p role="status" className="text-destructive text-xs">
          {t("starterAgentMissing")}
        </p>
      ) : null}
      {agent.managed_in ? (
        <p className="text-muted-foreground text-xs">
          {agent.model_label ? t("managedIn", { model: agent.model_label }) : t("managedInNoModel")}
        </p>
      ) : (
        <Profile agent={agent} />
      )}
      <Spend agent={agent} />
      <History agent={agent} />
    </div>
  );
}

function Profile({ agent }: { agent: SystemAgent }) {
  const t = useTranslations("teams.systemAgents");
  const tErrors = useTranslations("errors");
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const { update } = useSystemAgents(true);
  const saved = {
    enabled: agent.enabled,
    modelId: agent.model_profile_id,
    budget: agent.monthly_budget_usd === null ? "" : String(Number(agent.monthly_budget_usd)),
  };
  const [form, setForm] = useState(saved);
  const [pending, setPending] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (useChanged(JSON.stringify(saved))) setForm(saved);
  const changed = JSON.stringify(form) !== JSON.stringify(saved);
  const edit = (next: Partial<typeof form>) => {
    setForm((current) => ({ ...current, ...next }));
    setErrors({});
  };

  const save = async () => {
    const budget = form.budget.trim();
    if (budget !== "" && (!Number.isFinite(Number(budget)) || Number(budget) < 0)) {
      setErrors({ [BUDGET_FIELD]: t("invalid") });
      return;
    }
    if (form.enabled && form.modelId === null) {
      setErrors({ [MODEL_FIELD]: t("modelRequired") });
      return;
    }
    try {
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
      const problem = submitFailure(failure, { fields: [MODEL_FIELD, BUDGET_FIELD] }, tErrors);
      setErrors(problem.fields);
      if (problem.toast) toast.error(problem.toast);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <Label htmlFor={`system-agent-${agent.role}-enabled`}>{t("enabled")}</Label>
        <Switch
          id={`system-agent-${agent.role}-enabled`}
          checked={form.enabled}
          disabled={update.isPending}
          onCheckedChange={(enabled) => edit({ enabled })}
        />
      </div>
      <fieldset className="min-w-0 space-y-2" disabled={update.isPending}>
        <legend className="text-sm font-medium">{t("model")}</legend>
        <ModelProfilePicker
          profiles={profiles}
          profilesStatus={profilesStatus}
          value={form.modelId}
          onChange={(modelId) => edit({ modelId })}
          onCreationPendingChange={(creating) => setPending((count) => count + (creating ? 1 : -1))}
          allowAdd={can(Perm.connectionsManage)}
          disabled={update.isPending}
        />
        {errors[MODEL_FIELD] ? (
          <p className="text-destructive text-xs">{errors[MODEL_FIELD]}</p>
        ) : (
          <p className="text-muted-foreground text-xs">{t("modelHint")}</p>
        )}
      </fieldset>
      <FormField
        label={t("budget")}
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
          disabled={update.isPending}
          onChange={(event) => edit({ budget: event.target.value })}
        />
      </FormField>
      <Button onClick={save} disabled={!changed || update.isPending || pending > 0}>
        {update.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {t("save")}
      </Button>
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
    <p className="text-muted-foreground text-xs">
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
