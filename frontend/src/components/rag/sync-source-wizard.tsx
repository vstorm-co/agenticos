"use client";

import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Calendar, Check, Cog, Copy, Plus, Plug } from "lucide-react";

import { Dialog, DialogContent, DialogHeader, DialogTitle, Spinner } from "@/components/ui";
import { CloneStep } from "@/components/rag/sync-source-clone-step";
import { ConfigureStep } from "@/components/rag/sync-source-configure-step";
import { ConnectorStep } from "@/components/rag/sync-source-connector-step";
import { ScheduleStep } from "@/components/rag/sync-source-schedule-step";
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

  // --- clone mode ---
  const selectedIntegration = orgIntegrations.find((i) => i.id === cloneSourceId);

  const handleCloneSubmit = async () => {
    if (!cloneSourceId || !defaultCollection) return;
    await onClone?.(
      cloneSourceId,
      defaultCollection,
      cloneName.trim() || `${selectedIntegration?.name ?? t("integration")} (${defaultCollection})`,
    );
  };

  // --- new mode canAdvance ---
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
