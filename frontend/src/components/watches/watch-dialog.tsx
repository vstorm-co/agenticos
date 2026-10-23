"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

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
  Switch,
  Textarea,
} from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useMcpConnections, useOrganizations } from "@/hooks";
import { useWatchPresets, useWatches } from "@/hooks/use-watches";
import { submitFailure } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { allowedIntervals, cadenceLabel } from "@/lib/watch-cadence";
import type { Watch } from "@/lib/watches-api";
import { WatchAccount, useAccountName } from "./watch-account";

const CUSTOM = "custom";
const FIELDS = ["connection_id", "interval_minutes", "preset_key", "title", "instructions"];

interface Draft {
  connectionId: string;
  presetKey: string;
  title: string;
  instructions: string;
  urgent: boolean;
  interval: number;
  exclusions: string;
}

function startFrom(watch: Watch | undefined, connectionId: string | undefined): Draft {
  return {
    connectionId: watch?.connection_id ?? connectionId ?? "",
    presetKey: watch?.preset_key ?? CUSTOM,
    title: watch?.title ?? "",
    instructions: watch?.instructions ?? "",
    urgent: watch?.urgent ?? false,
    interval: watch?.interval_minutes ?? 60,
    exclusions: (watch?.exclusions ?? []).join("\n"),
  };
}

/**
 * Set up or change one watch (#2301): which of the person's own connections, a
 * ready-made thing to look for or their own words, how often, and whether the
 * urgent ones are sent at once. A preset's words are the console's, in the
 * person's language, and stay editable.
 */
export function WatchDialog({
  open,
  onOpenChange,
  watch,
  connectionId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  watch?: Watch;
  connectionId?: string;
}) {
  const t = useTranslations("watches");
  const tCadence = useTranslations("watches.cadence");
  const tErrors = useTranslations("errors");
  const { connections } = useMcpConnections();
  const presets = useWatchPresets();
  const { activeOrg } = useOrganizations();
  const { create, update } = useWatches();
  const accountName = useAccountName();
  const router = useRouter();
  const onRoutines = usePathname().endsWith(ROUTES.ROUTINES);
  const [draft, setDraft] = useState(() => startFrom(watch, connectionId));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const connection = connections.find((each) => each.id === draft.connectionId);
  const offered = presets.filter((preset) => preset.server === connection?.catalog_key);
  const floor = activeOrg?.proactive_watch_min_minutes ?? 15;
  const intervals = allowedIntervals(floor);
  const edit = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setErrors({});
  };
  const pick = (presetKey: string) => {
    const preset = offered.find((each) => each.key === presetKey);
    edit(
      preset
        ? {
            presetKey,
            title: t(`presets.${preset.key}.title`),
            instructions: t(`presets.${preset.key}.instructions`),
            urgent: preset.urgent,
            interval: Math.max(preset.interval_minutes, floor),
          }
        : { presetKey },
    );
  };

  const save = async () => {
    setSaving(true);
    try {
      if (watch) {
        await update({
          id: watch.id,
          changes: {
            title: draft.title.trim(),
            instructions: draft.instructions.trim(),
            urgent: draft.urgent,
            interval_minutes: draft.interval,
            exclusions: draft.exclusions.split("\n"),
          },
        });
      } else {
        await create({
          connection_id: draft.connectionId,
          preset_key: draft.presetKey === CUSTOM ? null : draft.presetKey,
          title: draft.title.trim(),
          instructions: draft.instructions.trim(),
          urgent: draft.urgent,
          interval_minutes: draft.interval,
        });
      }
      if (watch) {
        toast.success(t("saved"));
      } else {
        // Started from an account's menu, the watch would otherwise vanish into
        // a page the person has not seen: say where it lives and where its
        // findings go.
        toast.success(t("created"), {
          description: t("createdWhere"),
          action: onRoutines
            ? undefined
            : { label: t("seeIt"), onClick: () => router.push(ROUTES.ROUTINES) },
        });
      }
      onOpenChange(false);
    } catch (failure) {
      const problem = submitFailure(failure, { fields: FIELDS }, tErrors);
      setErrors(problem.fields);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  const ready =
    draft.connectionId !== "" && draft.title.trim() !== "" && draft.instructions.trim() !== "";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_COLUMN}>
        <DialogHeader>
          <DialogTitle>{watch ? t("editTitle") : t("newTitle")}</DialogTitle>
          <DialogDescription>{t("dialogDescription")}</DialogDescription>
        </DialogHeader>
        <div className={cn(DIALOG_BODY, "space-y-4")}>
          <FormField
            label={t("connection")}
            htmlFor="watch-connection"
            error={errors.connection_id ?? null}
          >
            <Select
              value={draft.connectionId}
              onValueChange={(next) => edit({ connectionId: next, presetKey: CUSTOM })}
              disabled={saving || watch !== undefined}
            >
              <SelectTrigger id="watch-connection">
                <SelectValue placeholder={t("connectionPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {connections.map((each) => (
                  <SelectItem
                    key={each.id}
                    value={each.id}
                    textValue={accountName(each.catalog_key, each.label ?? each.name).name}
                  >
                    <WatchAccount
                      server={each.catalog_key}
                      connectionName={each.label ?? each.name}
                    />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {!watch && offered.length > 0 && (
            <FormField label={t("preset")} htmlFor="watch-preset" error={errors.preset_key ?? null}>
              <div id="watch-preset" role="radiogroup" className="grid gap-2 sm:grid-cols-2">
                {[...offered.map((preset) => preset.key), CUSTOM].map((key) => (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={draft.presetKey === key}
                    disabled={saving}
                    onClick={() => pick(key)}
                    className={cn(
                      "rounded-xl border px-3 py-2 text-left text-sm transition-colors",
                      draft.presetKey === key
                        ? "border-foreground bg-muted"
                        : "border-input hover:border-foreground/40",
                    )}
                  >
                    {key === CUSTOM ? t("custom") : t(`presets.${key}.title`)}
                  </button>
                ))}
              </div>
            </FormField>
          )}
          <FormField label={t("name")} htmlFor="watch-title" error={errors.title ?? null}>
            <Input
              id="watch-title"
              maxLength={120}
              value={draft.title}
              disabled={saving}
              onChange={(event) => edit({ title: event.target.value })}
            />
          </FormField>
          <FormField
            label={t("instructions")}
            htmlFor="watch-instructions"
            description={t("instructionsHint")}
            error={errors.instructions ?? null}
          >
            <Textarea
              id="watch-instructions"
              rows={3}
              maxLength={2000}
              value={draft.instructions}
              disabled={saving}
              placeholder={t("instructionsPlaceholder")}
              onChange={(event) => edit({ instructions: event.target.value })}
            />
          </FormField>
          <FormField
            label={t("howOften")}
            htmlFor="watch-interval"
            error={errors.interval_minutes ?? null}
          >
            <Select
              value={String(draft.interval)}
              onValueChange={(value) => edit({ interval: Number(value) })}
              disabled={saving}
            >
              <SelectTrigger id="watch-interval">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {intervals.map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>
                    {cadenceLabel(minutes, tCadence)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="watch-urgent">{t("urgent")}</Label>
              <p className="text-muted-foreground text-xs">{t("urgentHint")}</p>
            </div>
            <Switch
              id="watch-urgent"
              checked={draft.urgent}
              disabled={saving}
              onCheckedChange={(urgent) => edit({ urgent })}
            />
          </div>
          {watch && (
            <FormField
              label={t("exclusions")}
              htmlFor="watch-exclusions"
              description={t("exclusionsHint")}
            >
              <Textarea
                id="watch-exclusions"
                rows={3}
                value={draft.exclusions}
                disabled={saving}
                onChange={(event) => edit({ exclusions: event.target.value })}
              />
            </FormField>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t("cancel")}
          </Button>
          <Button onClick={save} disabled={saving || !ready}>
            {watch ? t("save") : t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
