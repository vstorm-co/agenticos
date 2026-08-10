"use client";

import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { SyncSourceCreate } from "@/lib/rag-api";
import { cn } from "@/lib/utils";

const SYNC_MODES = [
  { value: "full", words: "modeFull" },
  { value: "new_only", words: "modeNewOnly" },
  { value: "update_only", words: "modeUpdateOnly" },
];

const SCHEDULE_PRESETS = [
  { value: 0, words: "cadenceManual" },
  { value: 60, words: "everyHour" },
  { value: 360, words: "everySixHours" },
  { value: 1440, words: "cadenceDaily" },
];

export function ScheduleStep({
  collections,
  form,
  setForm,
}: {
  collections: { name: string }[];
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
}) {
  const t = useTranslations("rag");
  return (
    <div className="space-y-5">
      {/* The picker appears when there is more than one collection to pick
          from, and `defaultCollection` seeds it rather than hiding it.

          It used to require `defaultCollection` to be absent, which no call
          site could satisfy: `/rag` passes the sidebar's selection, `kb/[id]`
          the base's own collection, and the org integration list an empty
          array (#434). So a source added from `/rag` - where the sync tab
          lists the whole organization's sources, not one collection's - was
          filed against whichever collection the sidebar happened to have
          selected, with nothing on screen saying which.

          One collection is not a choice, which is what keeps `kb/[id]` pinned
          to its own and the org list free of a control that would file an
          integration under a base. */}
      {collections.length > 1 && (
        <div className="space-y-1.5">
          <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
            {t("targetCollection")}
          </Label>
          <Select
            value={form.collection_name ?? ""}
            onValueChange={(val) => setForm((f) => ({ ...f, collection_name: val }))}
          >
            <SelectTrigger className="h-10 rounded-xl">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {collections.map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="space-y-2">
        <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
          {t("syncMode")}
        </Label>
        <div className="grid gap-2 sm:grid-cols-3">
          {SYNC_MODES.map((mode) => {
            const active = (form.sync_mode ?? "full") === mode.value;
            return (
              <button
                key={mode.value}
                type="button"
                onClick={() => setForm((f) => ({ ...f, sync_mode: mode.value }))}
                className={cn(
                  "rounded-xl border p-3 text-left transition-colors",
                  active
                    ? "border-brand bg-brand/[0.06]"
                    : "border-foreground/10 bg-card hover:border-foreground/30",
                )}
              >
                <p className="text-foreground text-sm font-semibold">{t(mode.words)}</p>
                <p className="text-foreground/55 mt-0.5 text-xs">{t(`${mode.words}Detail`)}</p>
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-2">
        <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
          {t("schedule")}
        </Label>
        <div className="flex flex-wrap gap-2">
          {SCHEDULE_PRESETS.map((p) => {
            const active = (form.schedule_minutes ?? 0) === p.value;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() =>
                  setForm((f) => ({ ...f, schedule_minutes: p.value === 0 ? null : p.value }))
                }
                className={cn(
                  "border-foreground/15 inline-flex rounded-full border px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
                  active
                    ? "bg-foreground text-background border-foreground"
                    : "text-foreground/65 hover:text-foreground hover:border-foreground/40",
                )}
              >
                {t(p.words)}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 pt-1">
          <Label htmlFor="custom-schedule" className="text-foreground/55 text-xs">
            {t("customMinutes")}
          </Label>
          <Input
            id="custom-schedule"
            type="number"
            min={0}
            placeholder={t("n0Manual")}
            value={form.schedule_minutes ?? ""}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                schedule_minutes: e.target.value ? Number(e.target.value) : null,
              }))
            }
            className="h-9 w-32 rounded-xl"
          />
        </div>
      </div>
    </div>
  );
}
