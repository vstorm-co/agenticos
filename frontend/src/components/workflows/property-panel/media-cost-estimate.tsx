"use client";

import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useWorkflowMediaEstimate } from "@/hooks/use-workflow-media-estimate";
import {
  isWorkflowMediaScopeCurrent,
  useWorkflowMediaScope,
} from "@/hooks/use-workflow-media-scope";
import { getErrorMessage } from "@/lib/api-error";
import { formatBytes } from "@/lib/utils";
import type {
  WorkflowMediaEstimateAssumption,
  WorkflowMediaEstimateRead,
  WorkflowMediaEstimateRequest,
} from "@/lib/workflows/types";

interface Props {
  request: WorkflowMediaEstimateRequest;
  disabled?: boolean;
}

/** An explicit read with no provider call; edits immediately remove the previous estimate. */
export function MediaCostEstimate(props: Props) {
  const scope = useWorkflowMediaScope();
  return <ScopedEstimate key={JSON.stringify([scope, props.request])} {...props} scope={scope} />;
}

function ScopedEstimate({ request, disabled, scope }: Props & { scope: string }) {
  const t = useTranslations("workflows");
  const tErrors = useTranslations("errors");
  const estimate = useWorkflowMediaEstimate(request, scope);
  const hasKey =
    typeof request.config.secret_id === "string" && request.config.secret_id.trim() !== "";
  const locked = disabled || !hasKey || !isWorkflowMediaScopeCurrent(scope) || estimate.isPending;
  return (
    <div className="space-y-2 border-t pt-4">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={locked}
        onClick={() => {
          if (!locked) estimate.mutate();
        }}
      >
        {t(estimate.isPending ? "mediaEstimateLoading" : "mediaEstimateCalculate")}
      </Button>
      <p className="text-muted-foreground text-xs">
        {t(hasKey ? "mediaEstimateNoCharge" : "mediaEstimateChooseKey")}
      </p>
      {estimate.error !== null && (
        <p role="alert" className="text-destructive text-xs">
          {getErrorMessage(estimate.error, tErrors, t("mediaEstimateError")) ||
            t("mediaEstimateError")}
        </p>
      )}
      {!estimate.isPending && estimate.data !== undefined && (
        <EstimateResult estimate={estimate.data} />
      )}
    </div>
  );
}

function EstimateResult({ estimate }: { estimate: WorkflowMediaEstimateRead }) {
  const t = useTranslations("workflows");
  const locale = useLocale();
  const usd = (value: string) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 6,
    }).format(Number(value));
  return (
    <div className="space-y-2 text-xs" aria-live="polite">
      <p className="font-medium tabular-nums">
        {t("mediaEstimateReservation", { amount: usd(estimate.reservation_usd) })}
      </p>
      <p className="text-muted-foreground">
        {t("mediaEstimateStorage", { size: formatBytes(estimate.reserved_bytes) })}
      </p>
      <p className="text-muted-foreground">
        {t("mediaPricingAsOf", { date: estimate.pricing_as_of })}
      </p>
      {estimate.configured_max_cost_usd !== null && (
        <p>{t("mediaEstimateMaximum", { amount: usd(estimate.configured_max_cost_usd) })}</p>
      )}
      {!estimate.sufficient_max_cost_usd && (
        <p role="alert" className="text-destructive">
          {t(
            estimate.configured_max_cost_usd === null
              ? "mediaEstimateNeedsMaximum"
              : "mediaEstimateDeficit",
            {
              amount: usd(
                estimate.configured_max_cost_usd === null
                  ? estimate.reservation_usd
                  : estimate.deficit_usd,
              ),
            },
          )}
        </p>
      )}
      <details>
        <summary className="cursor-pointer font-medium">{t("mediaEstimateAssumptions")}</summary>
        <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-4">
          {estimate.assumptions.map((assumption) => (
            <Assumption key={assumption.code} value={assumption} usd={usd} />
          ))}
        </ul>
      </details>
    </div>
  );
}

const SIMPLE = {
  conservative_reservation: "mediaEstimateConservative",
  single_submission: "mediaEstimateSingleSubmission",
  dispatch_limits_rechecked: "mediaEstimateRechecked",
  unresolved_hold_retained: "mediaEstimateUnresolved",
  text_only: "mediaEstimateTextOnly",
} as const;

function Assumption({
  value,
  usd,
}: {
  value: WorkflowMediaEstimateAssumption;
  usd: (value: string) => string;
}) {
  const t = useTranslations("workflows");
  switch (value.code) {
    case "image_token_ceiling":
      return (
        <li>
          {t("mediaEstimateImageTokens", {
            input: value.max_input_tokens,
            output: value.max_output_tokens,
          })}
        </li>
      );
    case "image_tool_ceiling":
      return (
        <li>
          {t("mediaEstimateImageTool", {
            characters: value.prompt_max_characters,
            quality: t(`mediaEstimateQuality.${value.quality}`),
            size: value.size,
            estimate: usd(value.output_estimate_usd),
            ceiling: usd(value.output_ceiling_usd),
          })}
        </li>
      );
    case "video_duration_rate":
      return (
        <li>
          {t("mediaEstimateVideoRate", {
            seconds: value.seconds,
            resolution: value.resolution,
            rate: usd(value.usd_per_second),
          })}
          {value.uses_model_maximum && ` ${t("mediaEstimateVideoMaximum")}`}
          {value.sound_on_ceiling && ` ${t("mediaEstimateVideoSound")}`}
        </li>
      );
    default:
      return <li>{t(SIMPLE[value.code])}</li>;
  }
}
