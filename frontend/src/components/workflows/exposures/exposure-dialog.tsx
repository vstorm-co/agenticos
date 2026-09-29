"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { parseRunInput } from "@/components/workflows/runs/start-run-dialog";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import type {
  ExposureAdapter,
  WorkflowExposureCreate,
  WorkflowExposureRead,
} from "@/lib/workflows/types";

import {
  type CadenceDraft,
  type CadenceMode,
  cadenceBody,
  cadenceDraftOf,
  DEFAULT_CADENCE,
} from "./cadence";

interface ExposureDialogProps {
  adapter: ExposureAdapter;
  /** The schedule being edited; absent when creating. A webhook is never edited here. */
  exposure?: WorkflowExposureRead;
  busy?: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: WorkflowExposureCreate) => void;
}

const UNITS: IntervalUnit[] = ["minutes", "hours", "days"];

/**
 * Create a webhook or a schedule, or edit a schedule's name, cadence and input.
 *
 * A webhook needs only a name: what it runs with is whatever the delivery's
 * body says. A schedule has no caller, so the payload `core.input` hands the
 * graph is written here, the same JSON object a manual start takes.
 */
export function ExposureDialog({
  adapter,
  exposure,
  busy,
  onOpenChange,
  onSubmit,
}: ExposureDialogProps) {
  const t = useTranslations("pages.workflows");
  const schedule = adapter === "schedule";
  const [name, setName] = useState(exposure?.name ?? "");
  const [cadence, setCadence] = useState<CadenceDraft>(
    exposure ? cadenceDraftOf(exposure) : DEFAULT_CADENCE,
  );
  const [text, setText] = useState(
    exposure && Object.keys(exposure.run_input).length > 0
      ? JSON.stringify(exposure.run_input, null, 2)
      : "{\n  \n}",
  );
  const parsed = parseRunInput(text);
  const body = cadenceBody(cadence);
  const set = (patch: Partial<CadenceDraft>) => setCadence((draft) => ({ ...draft, ...patch }));
  const trimmed = name.trim() || null;
  // What pressing Create sends, or null while the form cannot be scheduled.
  const submission: WorkflowExposureCreate | null = !schedule
    ? { adapter, name: trimmed }
    : body !== null && typeof parsed !== "string"
      ? { adapter, name: trimmed, run_input: parsed, ...body }
      : null;

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {exposure
              ? t("exposureEditTitle")
              : schedule
                ? t("exposureNewScheduleTitle")
                : t("exposureNewWebhookTitle")}
          </DialogTitle>
          <DialogDescription>
            {schedule ? t("exposureScheduleDescription") : t("exposureWebhookDescription")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="exposure-name">{t("exposureName")}</Label>
            <Input
              id="exposure-name"
              value={name}
              maxLength={120}
              placeholder={schedule ? t("exposureDefaultSchedule") : t("exposureDefaultWebhook")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          {schedule && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="exposure-cadence">{t("exposureCadence")}</Label>
                <Select
                  value={cadence.mode}
                  onValueChange={(mode) => set({ mode: mode as CadenceMode })}
                >
                  <SelectTrigger id="exposure-cadence">
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
                    <Label htmlFor="exposure-count">{t("exposureEvery")}</Label>
                    <Input
                      id="exposure-count"
                      type="number"
                      min={1}
                      inputMode="numeric"
                      value={cadence.count}
                      onChange={(event) => set({ count: event.target.value })}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="exposure-unit">{t("exposureUnit")}</Label>
                    <Select
                      value={cadence.unit}
                      onValueChange={(unit) => set({ unit: unit as IntervalUnit })}
                    >
                      <SelectTrigger id="exposure-unit">
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
                  <Label htmlFor="exposure-time">{t("exposureTime")}</Label>
                  <Input
                    id="exposure-time"
                    type="time"
                    value={cadence.time}
                    onChange={(event) => set({ time: event.target.value })}
                  />
                </div>
              )}
              {cadence.mode === "cron" && (
                <div className="space-y-1.5">
                  <Label htmlFor="exposure-cron">{t("exposureCron")}</Label>
                  <Input
                    id="exposure-cron"
                    className="font-mono"
                    value={cadence.cron}
                    onChange={(event) => set({ cron: event.target.value })}
                  />
                </div>
              )}
              {body === null && (
                <p className="text-destructive text-xs">{t("exposureCadenceInvalid")}</p>
              )}
              <p className="text-muted-foreground text-xs">{t("exposureUtcNote")}</p>
              <div className="space-y-1.5">
                <Label>{t("exposureInput")}</Label>
                <CodeArea
                  name="input.json"
                  aria-label={t("exposureInput")}
                  value={text}
                  onChange={setText}
                  className="min-h-28"
                />
                {typeof parsed === "string" && (
                  <p className="text-destructive text-xs">{t(`startRunInputInvalid.${parsed}`)}</p>
                )}
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={submission === null || busy}
            onClick={() => submission && onSubmit(submission)}
          >
            {exposure ? t("exposureSave") : t("exposureCreate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
