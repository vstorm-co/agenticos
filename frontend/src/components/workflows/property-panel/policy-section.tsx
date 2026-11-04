"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import type { NodeDefinition, NodeInstance, NodePolicy, Uuid } from "@/lib/workflows/types";

interface PolicySectionProps {
  definition: NodeDefinition;
  node: NodeInstance;
  disabled?: boolean;
  updateNodePolicy: (nodeId: Uuid, policy: NodePolicy | null) => void;
}

const DEFAULT_ATTEMPTS = "default";
const ATTEMPT_CHOICES = [1, 2, 3, 5, 10];

/** A policy with nothing set is no policy - the node keeps the deployment's defaults. */
function normalized(policy: NodePolicy): NodePolicy | null {
  const routes = policy.on_error === "route";
  if (!policy.timeout_seconds && !policy.retry && !routes) return null;
  return {
    ...(policy.timeout_seconds ? { timeout_seconds: policy.timeout_seconds } : {}),
    ...(policy.retry ? { retry: policy.retry } : {}),
    ...(routes ? { on_error: "route" as const } : {}),
  };
}

/**
 * How one step behaves when its call is slow or fails - the node's `policy`.
 *
 * A time limit, how many tries it gets and how long it waits between them, and
 * whether a failure leaves by an `error` port for an error handler instead of
 * failing the run. Retries are offered only where repeating the call is safe
 * (`retry_guarantee` other than `none`) - publishing refuses them elsewhere - so
 * the control says why it is off rather than being a choice the next publish
 * turns down.
 */
export function PolicySection({
  definition,
  node,
  disabled,
  updateNodePolicy,
}: PolicySectionProps) {
  const t = useTranslations("workflows");
  const id = useId();
  const policy: NodePolicy = node.policy ?? {};
  const retry = policy.retry ?? null;
  const retriesAllowed = definition.retry_guarantee !== "none";

  const write = (next: NodePolicy) => updateNodePolicy(node.id, normalized(next));

  return (
    <section className="space-y-3" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="text-muted-foreground text-xs font-medium tracking-wide">
        {t("policySection")}
      </h3>

      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <Label htmlFor={`${id}-route`}>{t("policyRouteLabel")}</Label>
          <p className="text-muted-foreground text-xs">{t("policyRouteHint")}</p>
        </div>
        <Switch
          id={`${id}-route`}
          checked={policy.on_error === "route"}
          disabled={disabled}
          onCheckedChange={(checked) =>
            write({ ...policy, on_error: checked ? "route" : "fail_run" })
          }
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor={`${id}-attempts`}>{t("policyAttemptsLabel")}</Label>
          <Select
            value={retry ? String(retry.max_attempts) : DEFAULT_ATTEMPTS}
            disabled={disabled || !retriesAllowed}
            onValueChange={(value) =>
              write({
                ...policy,
                retry:
                  value === DEFAULT_ATTEMPTS
                    ? null
                    : { ...(retry ?? {}), max_attempts: Number(value) },
              })
            }
          >
            <SelectTrigger id={`${id}-attempts`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_ATTEMPTS}>{t("policyAttemptsDefault")}</SelectItem>
              {ATTEMPT_CHOICES.map((count) => (
                <SelectItem key={count} value={String(count)}>
                  {t("policyAttemptsCount", { count })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-timeout`}>{t("policyTimeoutLabel")}</Label>
          <Input
            id={`${id}-timeout`}
            type="number"
            min={1}
            max={3600}
            inputMode="numeric"
            placeholder={t("policyTimeoutNone")}
            disabled={disabled}
            value={policy.timeout_seconds ?? ""}
            onChange={(event) => {
              const seconds = Number(event.target.value);
              write({
                ...policy,
                timeout_seconds: event.target.value === "" || !(seconds > 0) ? null : seconds,
              });
            }}
          />
        </div>
      </div>
      {!retriesAllowed && (
        <p className="text-muted-foreground text-xs">{t("policyRetriesUnsafe")}</p>
      )}

      {retry !== null && retry.max_attempts > 1 && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor={`${id}-backoff`}>{t("policyBackoffLabel")}</Label>
            <Select
              value={retry.backoff ?? "exponential"}
              disabled={disabled}
              onValueChange={(value) =>
                write({
                  ...policy,
                  retry: { ...retry, backoff: value as "fixed" | "exponential" },
                })
              }
            >
              <SelectTrigger id={`${id}-backoff`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="exponential">{t("policyBackoffExponential")}</SelectItem>
                <SelectItem value="fixed">{t("policyBackoffFixed")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${id}-delay`}>{t("policyDelayLabel")}</Label>
            <Input
              id={`${id}-delay`}
              type="number"
              min={1}
              inputMode="numeric"
              disabled={disabled}
              value={retry.base_delay_seconds ?? 2}
              onChange={(event) => {
                const seconds = Number(event.target.value);
                if (seconds > 0)
                  write({ ...policy, retry: { ...retry, base_delay_seconds: seconds } });
              }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
