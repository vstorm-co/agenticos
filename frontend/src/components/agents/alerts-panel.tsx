"use client";

import Link from "next/link";
import { CircleDollarSign, Hand, PieChart, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  Label,
  Switch,
} from "@/components/ui";
import { MemberIdentity, displayName } from "@/components/orgs/member-identity";
import { MemberPicker } from "@/components/orgs/member-picker";
import type { IdentifiedMember } from "@/components/orgs/member-identity";
import { useMembers } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { DEFAULT_NOTIFICATIONS } from "@/lib/agent-spec";
import { useOrgStore } from "@/stores";
import type { AlertAudience, AlertSpec, NotificationSpec } from "@/types/agents";
import { useTranslations } from "next-intl";

interface AlertsPanelProps {
  value: NotificationSpec | undefined;
  onChange: (notifications: NotificationSpec) => void;
  disabled?: boolean;
}

/** How many people are named, in words rather than a bare digit. */
function chosenCount(count: number): string {
  if (count === 0) return "Choose people";
  return count === 1 ? "1 person" : `${count} people`;
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
  const t = useTranslations("agents");
  /* v8 ignore next -- the selector never runs: every test here mocks the store */
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
        <CardTitle>{t("alerts")}</CardTitle>
        <CardDescription>
          Who hears about this agent when nobody is watching it. A run started from chat says what
          happened on screen; the same run started by a schedule, a channel or the API stops
          silently, and this is what closes that gap.{" "}
          <Link href={ROUTES.SETTINGS_NOTIFICATIONS} className="underline underline-offset-4">
            {t("yourOwnSwitches")}
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
            members={members}
            disabled={disabled}
            onChange={(alert) => edit(meta.key, alert)}
          />
        ))}

        <p className="text-muted-foreground text-xs">{t("organizationAposSOwn")}</p>
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
  members: IdentifiedMember[];
  disabled?: boolean;
  onChange: (alert: AlertSpec) => void;
}) {
  const t = useTranslations("agents");
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
      ? t("nobodySetHearAdd")
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
        <div className="mt-4 space-y-4 pl-12">
          {/* Checkboxes with real labels rather than a row of pills. Four pills
              with their hints hidden in `title` attributes was the odd one out in
              this app - nothing else picks several things that way - and a
              `title` is invisible on a touch screen and to a keyboard. */}
          <fieldset disabled={disabled} className="space-y-2">
            <legend className="text-muted-foreground text-xs font-medium">
              {t("whoHearsAbout")}
            </legend>
            {meta.audiences.map((audience) => {
              const id = `${meta.key}-${audience}`;
              return (
                <div key={audience} className="flex items-start gap-2.5">
                  <Checkbox
                    id={id}
                    checked={alert.to.includes(audience)}
                    disabled={disabled}
                    // Named with the alert as well as the audience. Three alerts
                    // offer the same four audiences, so the label alone is not a
                    // unique name - a screen reader would announce four identical
                    // "Specific people" and none of them would say which alert.
                    aria-label={`${meta.label}: ${AUDIENCE_LABEL[audience]}`}
                    onCheckedChange={() => toggleAudience(audience)}
                  />
                  <div className="-mt-0.5 min-w-0">
                    <Label htmlFor={id} className="text-sm font-normal">
                      {AUDIENCE_LABEL[audience]}
                    </Label>
                    <p className="text-muted-foreground text-xs">{AUDIENCE_HINT[audience]}</p>
                  </div>
                </div>
              );
            })}
          </fieldset>

          {alert.to.includes("chosen") &&
            (members.length === 0 ? (
              <p className="text-muted-foreground text-xs">{t("noMembersChooseFrom")}</p>
            ) : (
              <div className="space-y-2">
                <MemberPicker
                  members={members}
                  selected={alert.user_ids}
                  onToggle={toggleMember}
                  label={chosenCount}
                  scope={meta.label}
                  disabled={disabled}
                />

                {alert.user_ids.length > 0 && (
                  <ul className="space-y-1.5">
                    {alert.user_ids.map((userId) => {
                      const member = members.find((entry) => entry.user_id === userId);
                      const label = member === undefined ? userId : displayName(member);
                      return (
                        <li
                          key={userId}
                          className="border-border flex items-center gap-2 rounded-md border px-2.5 py-1.5"
                        >
                          {/* A member the listing no longer has - removed from the
                              organization since this was saved - still has to be
                              removable, so the id stands in rather than the row
                              vanishing and leaving nothing to click. */}
                          {member === undefined ? (
                            <span className="min-w-0 flex-1 truncate font-mono text-xs">
                              {userId}
                            </span>
                          ) : (
                            <MemberIdentity member={member} className="min-w-0 flex-1" />
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={disabled}
                            aria-label={`${meta.label}: remove ${label}`}
                            onClick={() => toggleMember(userId)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            ))}

          {problem && (
            // A span rather than a `Badge`: that component renders a `div`, and a
            // `div` inside a `p` is invalid HTML that React resolves by
            // restructuring the DOM - which shows up as a hydration error.
            <p className="text-destructive text-xs">
              <span className="mr-1.5 font-medium">{t("refusedAtSave")}</span>
              {problem}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
