"use client";

import Link from "next/link";
import { CircleDollarSign, Hand, PieChart } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle, Switch } from "@/components/ui";
import { useMembers } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { DEFAULT_NOTIFICATIONS } from "@/lib/agent-spec";
import { useOrgStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { AlertAudience, AlertSpec, NotificationSpec } from "@/types/agents";

interface AlertsPanelProps {
  value: NotificationSpec | undefined;
  onChange: (notifications: NotificationSpec) => void;
  disabled?: boolean;
}

/** Which alert, and everything that has to be said about it in the UI. */
interface AlertKindMeta {
  key: keyof NotificationSpec;
  label: string;
  trigger: string;
  icon: LucideIcon;
  /** `initiator` is refused on a usage report: it covers a period, not a run. */
  audiences: AlertAudience[];
}

const AUDIENCE_LABEL: Record<AlertAudience, string> = {
  admins: "Admins",
  owner: "The agent's owner",
  initiator: "Whoever started the run",
  chosen: "Specific people",
};

const AUDIENCE_HINT: Record<AlertAudience, string> = {
  admins: "This organization's owners and admins, plus the deployment's app admins.",
  owner: "The person who would fix this agent's configuration.",
  initiator: "Nobody, for a run a schedule or a channel started.",
  chosen: "A standing list, whoever happened to run it.",
};

const ALERTS: readonly AlertKindMeta[] = [
  {
    key: "budget",
    label: "Budget alerts",
    trigger: "A run stopped because this agent reached its own monthly cap.",
    icon: CircleDollarSign,
    audiences: ["admins", "owner", "initiator", "chosen"],
  },
  {
    key: "approvals",
    label: "Approval requests",
    trigger: "A tool call parked, and the run is waiting on a person to decide.",
    icon: Hand,
    audiences: ["admins", "owner", "initiator", "chosen"],
  },
  {
    key: "usage",
    label: "Usage reports",
    trigger: "Weekly and monthly, what this agent alone has spent.",
    icon: PieChart,
    // No `initiator`: a report covers a period rather than a run, so there is
    // no such person. The backend refuses it, and offering it here would be
    // offering a save that fails.
    audiences: ["admins", "owner", "chosen"],
  },
];

/**
 * Who hears about this agent, per kind of alert.
 *
 * These used to be three switches on `/settings/notifications`, one per person,
 * for the whole deployment. That made the noisy agent and the one nobody may
 * miss the same setting: the only way to quieten the first was to go deaf to the
 * second. The alerts are about an agent, so they are configured on one.
 *
 * The per-person switches have not gone away and are not duplicated here. They
 * are an opt-out and only ever subtract: an agent can decide the admins should
 * hear about it, and an admin can still decide they do not want budget mail.
 * Nothing an author writes here conscripts somebody into an inbox.
 *
 * The organization's own monthly cap is deliberately not on this panel. It stops
 * every agent in the organization, its ceiling is set in the organization's
 * settings, and an agent's author cannot raise it - so its alert goes to the
 * people who can, and no agent can redirect or silence it.
 */
export function AlertsPanel({ value, onChange, disabled }: AlertsPanelProps) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  // Defaulted rather than guarded: the API always answers with a full block, and
  // an agent created in this session has not been round-tripped yet.
  const spec = value ?? DEFAULT_NOTIFICATIONS;

  const edit = (key: keyof NotificationSpec, alert: AlertSpec) =>
    onChange({ ...spec, [key]: alert });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Alerts</CardTitle>
        <CardDescription>
          Who hears about this agent when nobody is watching it. A run started from chat says what
          happened on screen; the same run started by a schedule, a channel or the API stops
          silently, and this is what closes that gap.{" "}
          <Link href={ROUTES.SETTINGS_NOTIFICATIONS} className="underline underline-offset-4">
            Your own switches
          </Link>{" "}
          still apply on top and can only ever remove you from a list.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {ALERTS.map((meta) => (
          <AlertRow
            key={meta.key}
            meta={meta}
            alert={spec[meta.key]}
            members={members.map((member) => ({
              user_id: member.user_id,
              label: member.full_name ?? member.email,
            }))}
            disabled={disabled}
            onChange={(alert) => edit(meta.key, alert)}
          />
        ))}

        <p className="text-muted-foreground text-xs">
          The organization&apos;s own monthly cap is not here. It stops every agent in the
          organization and an agent&apos;s author cannot raise it, so its alert always goes to the
          admins.
        </p>
      </CardContent>
    </Card>
  );
}

function AlertRow({
  meta,
  alert,
  members,
  disabled,
  onChange,
}: {
  meta: AlertKindMeta;
  alert: AlertSpec;
  members: { user_id: string; label: string }[];
  disabled?: boolean;
  onChange: (alert: AlertSpec) => void;
}) {
  const toggleAudience = (audience: AlertAudience) => {
    const on = alert.to.includes(audience);
    const to = on ? alert.to.filter((entry) => entry !== audience) : [...alert.to, audience];
    onChange({
      ...alert,
      to,
      // Ids are only read when `chosen` is in `to`, and the backend refuses a
      // spec carrying ids without it - so dropping the audience drops the list
      // rather than leaving one the save would reject.
      user_ids: to.includes("chosen") ? alert.user_ids : [],
    });
  };

  const toggleMember = (userId: string) => {
    const user_ids = alert.user_ids.includes(userId)
      ? alert.user_ids.filter((entry) => entry !== userId)
      : [...alert.user_ids, userId];
    onChange({ ...alert, user_ids });
  };

  // The two shapes the backend refuses, said here rather than at save. Both are
  // reachable by clicking: switch an alert on and clear its audiences, or pick
  // "Specific people" and name nobody.
  const problem =
    alert.enabled && alert.to.length === 0
      ? "Nobody is set to hear this. Add an audience, or switch the alert off."
      : alert.to.includes("chosen") && alert.user_ids.length === 0
        ? "“Specific people” is chosen and nobody is named, so this would mail nobody."
        : null;

  return (
    <div className="border-border rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <meta.icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{meta.label}</p>
          <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">{meta.trigger}</p>
        </div>
        <Switch
          checked={alert.enabled}
          disabled={disabled}
          aria-label={meta.label}
          onCheckedChange={(enabled) =>
            onChange(
              // Switching on with no audience left would save a spec the backend
              // refuses, so the default audience comes back with it.
              enabled && alert.to.length === 0
                ? { ...alert, enabled, to: ["admins"] }
                : { ...alert, enabled },
            )
          }
        />
      </div>

      {alert.enabled && (
        <div className="mt-4 space-y-3 pl-12">
          <div className="flex flex-wrap gap-1.5">
            {meta.audiences.map((audience) => {
              const on = alert.to.includes(audience);
              return (
                <button
                  key={audience}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  aria-label={`${meta.label}: ${AUDIENCE_LABEL[audience]}`}
                  title={AUDIENCE_HINT[audience]}
                  disabled={disabled}
                  onClick={() => toggleAudience(audience)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs transition-colors",
                    on
                      ? "border-brand bg-brand/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-foreground/20",
                    disabled && "cursor-not-allowed opacity-60",
                  )}
                >
                  {AUDIENCE_LABEL[audience]}
                </button>
              );
            })}
          </div>

          {alert.to.includes("chosen") && (
            <div className="space-y-1.5">
              {members.length === 0 ? (
                <p className="text-muted-foreground text-xs">
                  No members to choose from - this organization is just you.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {members.map((member) => {
                    const on = alert.user_ids.includes(member.user_id);
                    return (
                      <button
                        key={member.user_id}
                        type="button"
                        role="checkbox"
                        aria-checked={on}
                        aria-label={`${meta.label}: ${member.label}`}
                        disabled={disabled}
                        onClick={() => toggleMember(member.user_id)}
                        className={cn(
                          "rounded-full border px-3 py-1 text-xs transition-colors",
                          on
                            ? "border-brand bg-brand/10 text-foreground"
                            : "border-border text-muted-foreground hover:border-foreground/20",
                          disabled && "cursor-not-allowed opacity-60",
                        )}
                      >
                        {member.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {problem && (
            // A span rather than a `Badge`: that component renders a `div`, and a
            // `div` inside a `p` is invalid HTML that React resolves by
            // restructuring the DOM - which shows up as a hydration error.
            <p className="text-destructive text-xs">
              <span className="mr-1.5 font-medium">Refused at save -</span>
              {problem}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
