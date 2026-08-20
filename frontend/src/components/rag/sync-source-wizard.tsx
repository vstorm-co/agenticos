"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Calendar, Cog, Copy, KeyRound, Plus, Plug } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  WizardNav,
  WizardSteps,
} from "@/components/ui";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { SourceAudienceNotice } from "@/components/rag/sync-source-audience-notice";
import { CloneStep } from "@/components/rag/sync-source-clone-step";
import { ConfigureStep } from "@/components/rag/sync-source-configure-step";
import { CredentialStep } from "@/components/rag/sync-source-credential-step";
import { ConnectorStep } from "@/components/rag/sync-source-connector-step";
import { ScheduleStep } from "@/components/rag/sync-source-schedule-step";
import type { ConnectorInfo, SyncSourceCreate, SyncSourceRead } from "@/lib/rag-api";
import type { KBScope } from "@/types/knowledge-base";
import { cn } from "@/lib/utils";
import { DIALOG_FORM } from "@/lib/dialog-widths";
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
   *
   * The scope travels with the name because it is what decides the audience:
   * `personal` is its owner, `org` is everyone who can view the collection, and
   * `app` is anybody in the deployment - which the last step now says out loud
   * (#982).
   */
  collections: { name: string; scope: KBScope }[];
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
type Step = "source" | "configure" | "credential" | "schedule";

/** Each step's word is in the catalog; `words` names the key. */
const STEPS: { id: Step; words: string; icon: typeof Plug }[] = [
  { id: "source", words: "stepSource", icon: Plug },
  { id: "configure", words: "stepConfigure", icon: Cog },
  // Between the configuration and the schedule, because it is the one thing a
  // source needs that is not configuration: the credential is a vault secret it
  // references, not a field it carries (#937).
  { id: "credential", words: "stepCredential", icon: KeyRound },
  { id: "schedule", words: "stepSchedule", icon: Calendar },
];

/** One spelling of "nothing is wrong with this config", for all three places. */
const NO_ERRORS: Readonly<Record<string, string>> = {};

const EMPTY_FORM: SyncSourceCreate = {
  name: "",
  connector_type: "",
  collection_name: null,
  config: {},
  secret_id: null,
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
  const tErrors = useTranslations("errors");
  const [mode, setMode] = useState<Mode>("new");
  const [step, setStep] = useState<Step>("source");
  const [form, setForm] = useState<SyncSourceCreate>({
    ...EMPTY_FORM,
    collection_name: defaultCollection ?? null,
  });
  const [cloneSourceId, setCloneSourceId] = useState<string>("");
  const [cloneName, setCloneName] = useState<string>("");
  const [configErrors, setConfigErrors] = useState<Readonly<Record<string, string>>>(NO_ERRORS);
  /**
   * Which filling-in of this wizard is on screen, counted from the first.
   *
   * A submission is answered after an `await`, by which time the dialog may
   * have been dismissed and reopened - the X and Escape stay live while a
   * create is pending. A ref rather than state because the answer has to read
   * what is true *now*, not the value its closure captured when it was sent;
   * an effect rather than the reset below because a ref may not be written
   * during render, and nothing renders from this one anyway.
   */
  const session = useRef(0);
  useEffect(() => {
    if (open) session.current += 1;
  }, [open]);

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
    setConfigErrors(NO_ERRORS);
  }

  const selectedConnector = useMemo(
    () => connectors.find((c) => c.type === form.connector_type),
    [connectors, form.connector_type],
  );

  // Which of the server's complaints this wizard can show beside an input. The
  // backend reports them below the document it was sent - `config.folder_id` -
  // and `submitFailure` matches a path by its leaf as well as in full.
  //
  // `secret_id` is in the list because it is a field of the form now rather than
  // a member of `config_schema`, and a refusal about a field nothing claims is a
  // refusal that becomes a toast (#937).
  const configFields = useMemo(
    () => [...Object.keys(selectedConnector?.config_schema ?? {}), "secret_id"],
    [selectedConnector],
  );

  const enabledConnectors = connectors.filter((c) => c.enabled);
  const hasOrgIntegrations = orgIntegrations.length > 0;

  const selectedIntegration = orgIntegrations.find((i) => i.id === cloneSourceId);

  /**
   * The collection this source will be filed under, and who that lets read it.
   *
   * Read from the picker's value where there is a picker and from
   * `defaultCollection` where the collection is pinned - which is the case the
   * issue's repro walks, so the sentence cannot be conditional on a control that
   * only appears when there is more than one collection to choose from (#982).
   */
  const target = collections.find(
    (c) =>
      c.name ===
      (mode === "clone" ? defaultCollection : (form.collection_name ?? defaultCollection)),
  );
  // Which connector's credential the sentence is about - the one being
  // configured, or the one the chosen integration already uses. A connector
  // declaring `secret_kind: "none"` has none, and the notice says so rather than
  // describing one that does not exist.
  const audienceConnector =
    mode === "clone"
      ? connectors.find((c) => c.type === selectedIntegration?.connector_type)
      : selectedConnector;

  const handleCloneSubmit = async () => {
    if (!cloneSourceId || !defaultCollection) return;
    await onClone?.(
      cloneSourceId,
      defaultCollection,
      cloneName.trim() || `${selectedIntegration?.name ?? t("integration")} (${defaultCollection})`,
    );
  };

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
    if (step === "credential") {
      // A connector needing no credential advances with nothing chosen; one that
      // needs a kind will not sync without it, so the wizard asks here rather
      // than letting the source be created and fail in a worker.
      if (!selectedConnector) return false;
      return selectedConnector.secret_kind === "none" || Boolean(form.secret_id);
    }
    if (step === "schedule") return true;
    return false;
  })();

  /**
   * Submit, and put a refusal back where it can be answered.
   *
   * The mutation is three steps behind the field that caused it: a connector
   * refusing a folder id is refusing something typed on the configure step,
   * and the reader is looking at the schedule step when it answers. So the
   * problems the server attributed to config fields go back to that step, with
   * it, and only what belongs to no input is announced.
   *
   * Unless the reader left. Dismissing the dialog mid-flight and reopening it
   * starts a new session, and the abandoned request's refusal is about a form
   * that no longer exists: marking an input or moving a step on the strength of
   * it would send somebody to fix a field they never filled in, on a wizard
   * whose connector is not even chosen yet. It is still said - a create that
   * failed is not nothing - and nothing else is touched.
   */
  const handleSubmit = async () => {
    const submittedIn = session.current;
    setConfigErrors(NO_ERRORS);
    try {
      await onSubmit({
        ...form,
        collection_name: form.collection_name ?? defaultCollection ?? null,
      });
    } catch (error) {
      if (session.current !== submittedIn) {
        toast.error(getErrorMessage(error, tErrors));
        return;
      }
      const failure = submitFailure(error, { fields: configFields }, tErrors);
      setConfigErrors(failure.fields);
      // To the step that holds the field, not always to `configure`: the
      // credential is its own step since #937, and jumping to the configuration
      // for a refused `secret_id` marks an input that is not on screen - which
      // is the same defect #897 fixed by moving the message out of a toast.
      const named = Object.keys(failure.fields);
      if (named.length > 0) setStep(named.includes("secret_id") ? "credential" : "configure");
      if (failure.toast) toast.error(failure.toast);
    }
  };

  const handleNext = () => {
    if (!canAdvance) return;
    if (mode === "clone") {
      handleCloneSubmit();
      return;
    }
    if (step === "source") setStep("configure");
    else if (step === "configure") setStep("credential");
    else if (step === "credential") setStep("schedule");
    else if (step === "schedule") handleSubmit();
  };

  const handleBack = () => {
    if (step === "configure") setStep("source");
    else if (step === "credential") setStep("configure");
    else if (step === "schedule") setStep("credential");
  };

  const isLastStep = mode === "clone" || step === "schedule";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("max-h-[90vh] overflow-hidden p-0", DIALOG_FORM)}>
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
            <WizardSteps
              steps={STEPS.map((s) => ({ id: s.id, label: t(s.words), icon: s.icon }))}
              current={step}
            />
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
                <ConfigureStep
                  connector={selectedConnector}
                  form={form}
                  // Editing an input drops its mark, the way every other form
                  // here does: a refusal about a value that has since been
                  // changed is a refusal about nothing.
                  setForm={(update) => {
                    setConfigErrors(NO_ERRORS);
                    setForm(update);
                  }}
                  errors={configErrors}
                />
              )}
              {step === "credential" && selectedConnector && (
                <CredentialStep
                  connector={selectedConnector}
                  form={form}
                  setForm={(update) => {
                    setConfigErrors(NO_ERRORS);
                    setForm(update);
                  }}
                  error={configErrors.secret_id}
                />
              )}
              {step === "schedule" && (
                <ScheduleStep collections={collections} form={form} setForm={setForm} />
              )}
            </>
          )}

          {/* On the step that decides the collection, and on the clone step,
              which decides the same thing for a credential somebody else
              scoped. Not on the earlier steps: the sentence names a collection
              and a credential, and neither is chosen yet. */}
          {(mode === "clone" ? Boolean(cloneSourceId) : step === "schedule") && (
            <SourceAudienceNotice
              scope={target?.scope}
              collectionName={target?.name}
              secretId={mode === "clone" ? selectedIntegration?.secret_id : form.secret_id}
              needsCredential={audienceConnector?.secret_kind !== "none"}
            />
          )}
        </div>

        <WizardNav
          backIsStep={mode === "new" && step !== "source"}
          backLabel={mode === "new" && step !== "source" ? t("back") : t("cancel")}
          onBack={mode === "new" && step !== "source" ? handleBack : () => onOpenChange(false)}
          nextLabel={
            isLastStep
              ? mode === "clone"
                ? t("useIntegration")
                : t("createSource")
              : t("continue")
          }
          onNext={handleNext}
          nextDisabled={!canAdvance}
          isLast={isLastStep}
          busy={Boolean(submitting) && isLastStep}
          busyLabel={mode === "clone" ? t("cloning") : t("creating3")}
        />
      </DialogContent>
    </Dialog>
  );
}
