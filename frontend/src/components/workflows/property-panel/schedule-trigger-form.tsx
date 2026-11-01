"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { parseRunInput } from "@/components/workflows/runs/start-run-dialog";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";
import type { IntervalUnit } from "@/lib/trigger-format";
import type { NodeInstance, Uuid } from "@/lib/workflows/types";

import { type CadenceDraft, type CadenceMode, cadenceBody, cadenceDraftOf } from "./cadence";

const UNITS: IntervalUnit[] = ["minutes", "hours", "days"];

interface ScheduleTriggerFormProps {
  node: NodeInstance;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
}

/**
 * The Schedule trigger's configuration: how often it runs, and the input every
 * run starts with - in the words a builder thinks in ("every 2 hours", "daily at
 * 09:00") rather than the seconds and crontab the node stores.
 *
 * Each edit is written into the node's config as soon as it schedules; while
 * the cadence or the input cannot be stored, the form says why and the config
 * keeps its last good value, so the draft never holds a schedule that could not
 * fire.
 */
export function ScheduleTriggerForm({
  node,
  disabled,
  updateNodeConfig,
}: ScheduleTriggerFormProps) {
  const t = useTranslations("pages.workflows");
  const config = node.config;
  const [cadence, setCadence] = useState<CadenceDraft>(() => cadenceDraftOf(config));
  const [text, setText] = useState(() => {
    const input = config["input"];
    return input !== null && typeof input === "object" && Object.keys(input).length > 0
      ? JSON.stringify(input, null, 2)
      : "{\n  \n}";
  });
  const body = cadenceBody(cadence);
  const parsed = parseRunInput(text);

  const change = (patch: Partial<CadenceDraft>) => {
    const next = { ...cadence, ...patch };
    setCadence(next);
    const stored = cadenceBody(next);
    if (stored !== null) updateNodeConfig(node.id, { ...config, ...stored });
  };
  const changeInput = (value: string) => {
    setText(value);
    const input = parseRunInput(value);
    if (typeof input !== "string") updateNodeConfig(node.id, { ...config, input });
  };

  return (
    <section className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="schedule-cadence">{t("exposureCadence")}</Label>
        <Select
          value={cadence.mode}
          disabled={disabled}
          onValueChange={(mode) => change({ mode: mode as CadenceMode })}
        >
          <SelectTrigger id="schedule-cadence">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="interval">{t("exposureCadenceInterval")}</SelectItem>
            <SelectItem value="daily">{t("exposureCadenceDaily")}</SelectItem>
            <SelectItem value="cron">{t("exposureCadenceCron")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {cadence.mode === "interval" && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="schedule-count">{t("exposureEvery")}</Label>
            <Input
              id="schedule-count"
              type="number"
              min={1}
              inputMode="numeric"
              disabled={disabled}
              value={cadence.count}
              onChange={(event) => change({ count: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="schedule-unit">{t("exposureUnit")}</Label>
            <Select
              value={cadence.unit}
              disabled={disabled}
              onValueChange={(unit) => change({ unit: unit as IntervalUnit })}
            >
              <SelectTrigger id="schedule-unit">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {UNITS.map((unit) => (
                  <SelectItem key={unit} value={unit}>
                    {t(`exposureUnits.${unit}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
      {cadence.mode === "daily" && (
        <div className="space-y-1.5">
          <Label htmlFor="schedule-time">{t("exposureTime")}</Label>
          <Input
            id="schedule-time"
            type="time"
            disabled={disabled}
            value={cadence.time}
            onChange={(event) => change({ time: event.target.value })}
          />
        </div>
      )}
      {cadence.mode === "cron" && (
        <div className="space-y-1.5">
          <Label htmlFor="schedule-cron">{t("exposureCron")}</Label>
          <Input
            id="schedule-cron"
            className="font-mono"
            disabled={disabled}
            value={cadence.cron}
            onChange={(event) => change({ cron: event.target.value })}
          />
        </div>
      )}
      {body === null && <p className="text-destructive text-xs">{t("exposureCadenceInvalid")}</p>}
      <p className="text-muted-foreground text-xs">{t("exposureUtcNote")}</p>
      <div className="space-y-1.5">
        <Label>{t("exposureInput")}</Label>
        <CodeArea
          name="input.json"
          aria-label={t("exposureInput")}
          value={text}
          onChange={changeInput}
          readOnly={disabled}
          className="min-h-28"
        />
        {typeof parsed === "string" && (
          <p className="text-destructive text-xs">{t(`startRunInputInvalid.${parsed}`)}</p>
        )}
      </div>
    </section>
  );
}
