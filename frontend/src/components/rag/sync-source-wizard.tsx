"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Calendar,
  Check,
  Cog,
  Copy,
  Database,
  Plus,
  Plug,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Spinner,
  Switch,
  Textarea,
} from "@/components/ui";
import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
import type { ConnectorInfo, SyncSourceCreate, SyncSourceRead } from "@/lib/rag-api";
import { cn } from "@/lib/utils";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

interface SyncSourceWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectors: ConnectorInfo[];
  /**
   * Every collection this caller will let the source be filed under.
   *
   * One entry pins it; more than one draws a picker on the schedule step. An
   * empty list is an integration no collection owns yet.
   */
  collections: { name: string }[];
  /** Which of {@link collections} the picker starts on, and what clone mode fills. */
  defaultCollection?: string;
  /** Existing org integrations (without this KB's collection_name) for "pick existing" flow. */
  orgIntegrations?: SyncSourceRead[];
  /** The connector list request failed; an empty list is not a fact yet. */
  connectorsFailed?: boolean;
  /** The org-integrations request failed, so the "use existing" offer is missing, not absent. */
  orgIntegrationsFailed?: boolean;
  onSubmit: (data: SyncSourceCreate) => Promise<void> | void;
  onClone?: (sourceId: string, collectionName: string, name: string) => Promise<void> | void;
  submitting?: boolean;
}

type Mode = "new" | "clone";
type Step = "source" | "configure" | "schedule";

/** Each step's word is in the catalog; `words` names the key. */
const STEPS: { id: Step; words: string; icon: typeof Plug }[] = [
  { id: "source", words: "stepSource", icon: Plug },
  { id: "configure", words: "stepConfigure", icon: Cog },
  { id: "schedule", words: "stepSchedule", icon: Calendar },
];

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

const EMPTY_FORM: SyncSourceCreate = {
  name: "",
  connector_type: "",
  collection_name: null,
  config: {},
  sync_mode: "full",
  schedule_minutes: null,
};

export function SyncSourceWizard({
  open,
  onOpenChange,
  connectors,
  collections,
  defaultCollection,
  orgIntegrations = [],
  connectorsFailed = false,
  orgIntegrationsFailed = false,
  onSubmit,
  onClone,
  submitting,
}: SyncSourceWizardProps) {
  const t = useTranslations("rag");
  const [mode, setMode] = useState<Mode>("new");
  const [step, setStep] = useState<Step>("source");
  const [form, setForm] = useState<SyncSourceCreate>({
    ...EMPTY_FORM,
    collection_name: defaultCollection ?? null,
  });
  const [cloneSourceId, setCloneSourceId] = useState<string>("");
  const [cloneName, setCloneName] = useState<string>("");

  // Reopening starts from the beginning, during render - an effect would show
  // the last wizard's answers for a frame before clearing them.
  //
  // Opening is the only thing that resets it. It used to watch
  // `defaultCollection` as well, which is derived on the page it comes from -
  // `chosen || collections[0]?.name` - so a background refetch that reordered
  // the list moved it on its own and threw away a half-filled form. The
  // collection the wizard was opened with is the one it is for.
  if (useChanged(open) && open) {
    setMode("new");
    setStep("source");
    setForm({ ...EMPTY_FORM, collection_name: defaultCollection ?? null });
    setCloneSourceId("");
    setCloneName("");
  }

  const selectedConnector = useMemo(
    () => connectors.find((c) => c.type === form.connector_type),
    [connectors, form.connector_type],
  );

  const stepIdx = STEPS.findIndex((s) => s.id === step);
  const enabledConnectors = connectors.filter((c) => c.enabled);
  const hasOrgIntegrations = orgIntegrations.length > 0;

  // clone mode
  const selectedIntegration = orgIntegrations.find((i) => i.id === cloneSourceId);

  const handleCloneSubmit = async () => {
    if (!cloneSourceId || !defaultCollection) return;
    await onClone?.(
      cloneSourceId,
      defaultCollection,
      cloneName.trim() || `${selectedIntegration?.name ?? t("integration")} (${defaultCollection})`,
    );
  };

  // new mode canAdvance
  const canAdvance = (() => {
    if (mode === "clone") {
      return Boolean(cloneSourceId) && Boolean(defaultCollection);
    }
    if (step === "source") return Boolean(form.connector_type) && Boolean(form.name.trim());
    if (step === "configure") {
      if (!selectedConnector) return false;
      const required = Object.entries(selectedConnector.config_schema).filter(
        ([, f]) => f.required,
      );
      return required.every(([key]) => {
        const v = form.config[key];
        return v !== undefined && v !== null && v !== "";
      });
    }
    if (step === "schedule") return true;
    return false;
  })();

  const handleNext = () => {
    if (!canAdvance) return;
    if (mode === "clone") {
      handleCloneSubmit();
      return;
    }
    if (step === "source") setStep("configure");
    else if (step === "configure") setStep("schedule");
    else if (step === "schedule")
      onSubmit({ ...form, collection_name: form.collection_name ?? defaultCollection ?? null });
  };

  const handleBack = () => {
    if (step === "configure") setStep("source");
    else if (step === "schedule") setStep("configure");
  };

  const isLastStep = mode === "clone" || step === "schedule";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-foreground/10 border-b px-6 py-4">
          <DialogTitle className="text-base font-semibold">{t("addSyncSource")}</DialogTitle>

          {/* Mode toggle - visible on the first step so user can switch between new/clone */}
          {hasOrgIntegrations && step === "source" && (
            <div className="border-foreground/10 mt-3 flex items-center gap-2 rounded-xl border p-1">
              <button
                type="button"
                onClick={() => setMode("new")}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                  mode === "new"
                    ? "bg-foreground text-background"
                    : "text-foreground/60 hover:text-foreground",
                )}
              >
                <Plus className="h-3 w-3" />
                {t("createNew")}
              </button>
              <button
                type="button"
                onClick={() => setMode("clone")}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                  mode === "clone"
                    ? "bg-foreground text-background"
                    : "text-foreground/60 hover:text-foreground",
                )}
              >
                <Copy className="h-3 w-3" />
                {t("useExisting")}
              </button>
            </div>
          )}

          {orgIntegrationsFailed && step === "source" && (
            // Unsaid, a failed org-integrations request is indistinguishable from
            // an organization that has none: the "Use existing" toggle never appears.
            <p className="text-destructive mt-2 text-xs">{t("orgIntegrationsLoadFailed")}</p>
          )}

          {/* Step indicator - only for new mode */}
          {mode === "new" && (
            <ol className="mt-3 flex items-center gap-2">
              {STEPS.map((s, i) => {
                const done = i < stepIdx;
                const active = s.id === step;
                return (
                  <li key={s.id} className="flex flex-1 items-center gap-2">
                    <div
                      className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors",
                        done && "bg-foreground text-background",
                        active && "bg-brand text-brand-foreground",
                        !done && !active && "bg-foreground/8 text-foreground/55",
                      )}
                    >
                      {done ? <Check className="h-3 w-3" /> : <s.icon className="h-3 w-3" />}
                    </div>
                    <span
                      className={cn(
                        "hidden font-mono text-[10px] tracking-wider uppercase sm:inline",
                        active || done ? "text-foreground" : "text-foreground/45",
                      )}
                    >
                      {t(s.words)}
                    </span>
                    {i < STEPS.length - 1 && (
                      <span
                        className={cn(
                          "h-px flex-1",
                          i < stepIdx ? "bg-foreground" : "bg-foreground/15",
                        )}
                      />
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </DialogHeader>

        <div className="max-h-[60vh] scrollbar-thin overflow-y-auto px-6 py-5">
          {mode === "clone" ? (
            <CloneStep
              integrations={orgIntegrations}
              cloneSourceId={cloneSourceId}
              setCloneSourceId={setCloneSourceId}
              cloneName={cloneName}
              setCloneName={setCloneName}
            />
          ) : (
            <>
              {step === "source" && (
                <ConnectorStep
                  connectors={enabledConnectors}
                  connectorsFailed={connectorsFailed}
                  form={form}
                  setForm={setForm}
                />
              )}
              {step === "configure" && selectedConnector && (
                <ConfigureStep connector={selectedConnector} form={form} setForm={setForm} />
              )}
              {step === "schedule" && (
                <ScheduleStep collections={collections} form={form} setForm={setForm} />
              )}
            </>
          )}
        </div>

        <div className="border-foreground/10 flex items-center justify-between border-t px-6 py-4">
          {mode === "new" && step !== "source" ? (
            <button
              type="button"
              onClick={handleBack}
              disabled={submitting}
              className="text-foreground/65 hover:text-foreground inline-flex items-center gap-1.5 text-sm font-medium"
            >
              <ArrowLeft className="h-4 w-4" />
              {t("back")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="text-foreground/65 hover:text-foreground text-sm font-medium"
            >
              {t("cancel")}
            </button>
          )}

          <button
            type="button"
            onClick={handleNext}
            disabled={!canAdvance || submitting}
            className="bg-foreground text-background hover:bg-foreground/90 disabled:bg-foreground/30 inline-flex items-center gap-1.5 rounded-full px-5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed"
          >
            {submitting && isLastStep ? (
              <>
                <Spinner className="h-3.5 w-3.5" />
                {mode === "clone" ? t("cloning") : t("creating3")}
              </>
            ) : isLastStep ? (
              <>
                {mode === "clone" ? t("useIntegration") : t("createSource")}
                <Check className="h-4 w-4" />
              </>
            ) : (
              <>
                {t("continue")}
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CloneStep({
  integrations,
  cloneSourceId,
  setCloneSourceId,
  cloneName,
  setCloneName,
}: {
  integrations: SyncSourceRead[];
  cloneSourceId: string;
  setCloneSourceId: (id: string) => void;
  cloneName: string;
  setCloneName: (name: string) => void;
}) {
  const t = useTranslations("rag");
  return (
    <div className="space-y-5">
      <p className="text-foreground/65 text-sm">{t("pickExistingOrgIntegration")}</p>
      <div className="space-y-2">
        <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
          {t("orgIntegrations")}
        </Label>
        <div className="space-y-2">
          {integrations.map((src) => {
            const isSelected = cloneSourceId === src.id;
            const brand = connectorBrand(src.connector_type);
            return (
              <button
                key={src.id}
                type="button"
                onClick={() => setCloneSourceId(src.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border p-3.5 text-left transition-colors",
                  isSelected
                    ? "border-brand bg-brand/[0.06]"
                    : "border-foreground/10 bg-card hover:border-foreground/30",
                )}
              >
                <span
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                    isSelected
                      ? "bg-brand text-brand-foreground"
                      : "bg-foreground/8 text-foreground",
                  )}
                >
                  {brand ? (
                    <BrandIcon name={brand} className="h-4 w-4" aria-hidden />
                  ) : (
                    <Database className="h-4 w-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-foreground text-sm font-semibold">{src.name}</p>
                  <p className="text-foreground/55 font-mono text-[10px] tracking-wider uppercase">
                    {src.connector_type}
                    {src.collection_name ? ` · ${src.collection_name}` : " · unassigned"}
                  </p>
                </div>
                {isSelected && <Check className="text-brand h-4 w-4 shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {cloneSourceId && (
        <div className="space-y-1.5">
          <Label
            htmlFor="clone-name"
            className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
          >
            {t("nameKbAposS")}
          </Label>
          <Input
            id="clone-name"
            placeholder={t("leaveEmptyAutoGenerate")}
            value={cloneName}
            onChange={(e) => setCloneName(e.target.value)}
            className="h-10 rounded-xl"
          />
        </div>
      )}
    </div>
  );
}

function ConnectorStep({
  connectors,
  connectorsFailed,
  form,
  setForm,
}: {
  connectors: ConnectorInfo[];
  connectorsFailed?: boolean;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
}) {
  const t = useTranslations("rag");
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label
          htmlFor="source-name"
          className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
        >
          {t("sourceName")}
        </Label>
        <Input
          id="source-name"
          placeholder={t("eGEngineeringDocs")}
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className="h-10 rounded-xl"
        />
      </div>

      <div className="space-y-2">
        <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
          {t("connector")}
        </Label>
        {connectorsFailed ? (
          // "No connectors enabled" is a statement about the deployment; a failed
          // request has not made it.
          <p className="border-destructive/30 text-destructive rounded-xl border px-4 py-3 text-sm">
            {t("connectorLoadFailed")}
          </p>
        ) : connectors.length === 0 ? (
          <p className="border-foreground/10 bg-foreground/[0.03] text-foreground/65 rounded-xl border px-4 py-3 text-sm">
            {t("noConnectorsEnabled")}
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {connectors.map((conn) => {
              const isSelected = form.connector_type === conn.type;
              const brand = connectorBrand(conn.type);
              return (
                <button
                  key={conn.type}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, connector_type: conn.type, config: {} }))}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-3.5 text-left transition-colors",
                    isSelected
                      ? "border-brand bg-brand/[0.06]"
                      : "border-foreground/10 bg-card hover:border-foreground/30",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                      isSelected
                        ? "bg-brand text-brand-foreground"
                        : "bg-foreground/8 text-foreground",
                    )}
                  >
                    {brand ? (
                      <BrandIcon name={brand} className="h-4 w-4" aria-hidden />
                    ) : (
                      <Database className="h-4 w-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground text-sm font-semibold">{conn.name}</p>
                    <p className="text-foreground/55 truncate font-mono text-[10px] tracking-wider uppercase">
                      {conn.type}
                    </p>
                  </div>
                  {isSelected && <Check className="text-brand h-4 w-4 shrink-0" />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ConfigureStep({
  connector,
  form,
  setForm,
}: {
  connector: ConnectorInfo;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
}) {
  const t = useTranslations("rag");
  const fields = Object.entries(connector.config_schema);

  if (fields.length === 0) {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <Cog className="text-foreground/45 mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          No additional configuration needed for{" "}
          <span className="text-foreground font-medium">{connector.name}</span>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-foreground/65 text-sm">
        {t.rich("configureRequiredFields", {
          name: connector.name,
          required: (chunks) => <span className="text-destructive">{chunks}</span>,
        })}
      </p>
      {fields.map(([key, field]) => (
        <div key={key} className="space-y-1.5">
          <Label
            htmlFor={`cfg-${key}`}
            className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
          >
            {field.label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>

          {field.type === "boolean" ? (
            <div className="flex items-center gap-3 py-1">
              <Switch
                id={`cfg-${key}`}
                checked={!!form.config[key]}
                onCheckedChange={(val) =>
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: val } }))
                }
              />
              {field.help && <span className="text-foreground/55 text-xs">{field.help}</span>}
            </div>
          ) : field.type === "textarea" ? (
            <>
              <Textarea
                id={`cfg-${key}`}
                placeholder={field.default !== undefined ? String(field.default) : ""}
                value={
                  form.config[key] !== undefined && form.config[key] !== null
                    ? String(form.config[key])
                    : ""
                }
                onChange={(e) =>
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: e.target.value } }))
                }
                className="min-h-[160px] rounded-xl font-mono text-xs"
                spellCheck={false}
              />
              {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
            </>
          ) : (
            <>
              <Input
                id={`cfg-${key}`}
                type={field.secret ? "password" : field.type === "integer" ? "number" : "text"}
                placeholder={field.default !== undefined ? String(field.default) : ""}
                value={
                  form.config[key] !== undefined && form.config[key] !== null
                    ? String(form.config[key])
                    : ""
                }
                onChange={(e) => {
                  const val =
                    field.type === "integer"
                      ? e.target.value
                        ? Number(e.target.value)
                        : ""
                      : e.target.value;
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: val } }));
                }}
                className="h-10 rounded-xl"
              />
              {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function ScheduleStep({
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
