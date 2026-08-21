"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { ConnectionKindIcon } from "./connection-kind-icon";
import { NO_FAILURE, submitFailure } from "@/lib/api-error";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useLocalSandboxService, useSecrets } from "@/hooks";
import type {
  SandboxConnectionInput,
  SandboxConnectionKind,
  SandboxConnectionRecord,
  SandboxRuntime,
} from "@/lib/sandbox-connections-api";
import { RuntimeField } from "./runtime-field";
import { useTranslations } from "next-intl";
import { DIALOG_WIDE } from "@/lib/dialog-sizes";

interface ConnectionDialogProps {
  /**
   * The row being edited, or `null` to register a new one.
   *
   * Read once, when this component mounts. The page mounts it only while it is
   * open, which is what makes that safe: an effect that re-synced state from
   * props would be a cascading render, and the version without one showed the
   * previous row's values the second time somebody clicked Edit.
   */
  editing: SandboxConnectionRecord | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: SandboxConnectionInput & { is_active?: boolean }) => Promise<void>;
}

/**
 * What a key stored from this form is for.
 *
 * Two purposes rather than one because they are two different services with two
 * different tokens, and a picker offering a Daytona key for a `sandboxd` service
 * is a picker that authenticates the wrong host.
 */
const PURPOSE: Record<SandboxConnectionKind, string> = {
  docker: "sandboxd",
  daytona: "daytona",
};

const SUGGESTED_NAME: Record<SandboxConnectionKind, string> = {
  docker: "secretNameDocker",
  daytona: "secretNameDaytona",
};

interface FormState {
  name: string;
  kind: SandboxConnectionKind;
  baseUrl: string;
  /** Whether somebody has typed in the address, which stops it being prefilled. */
  urlTouched: boolean;
  secretId: string | null;
  defaultRuntime: string;
  isDefault: boolean;
  isActive: boolean;
}

function initialState(editing: SandboxConnectionRecord | null, defaultName: string): FormState {
  return {
    // Filled in rather than suggested. A placeholder is a name nobody has typed,
    // so the form opened invalid and the first thing an operator did was type
    // the two words the box was already showing them. Editing keeps its own.
    name: editing?.name ?? defaultName,
    kind: editing?.kind ?? "docker",
    baseUrl: editing?.base_url ?? "",
    urlTouched: editing !== null,
    secretId: editing?.secret_id ?? null,
    defaultRuntime: editing?.default_runtime ?? "",
    isDefault: editing?.is_default ?? false,
    isActive: editing?.is_active ?? true,
  };
}

/**
 * Whether this is worth submitting.
 *
 * The backend refuses the same two things, and refusing them here means an
 * operator is told while the form is open rather than by a toast afterwards. A
 * container connection with no address resolves and then fails to connect on
 * every session; that is not a state worth being able to save.
 */
function isComplete(form: FormState, baseUrl: string): boolean {
  if (form.name.trim().length === 0) return false;
  return form.kind !== "docker" || baseUrl.trim().length > 0;
}

/**
 * What this dialog can mark, for `submitFailure`.
 *
 * The address, because every refusal the service and the probe give about one -
 * a shape that cannot work, a host that does not answer, a port answering HTML
 * - names `base_url` (#891). And the name, through `identifiedBy`: a duplicate
 * is a 409 about a row that exists, which only this form can place.
 */
const FORM = { fields: ["base_url"], identifiedBy: "name" } as const;

/**
 * Register or edit a place sandboxes run.
 *
 * The credential is chosen from the vault or added inline; it is never typed into
 * this form's own state and never comes back from the server, which is what keeps
 * a token that can run commands on a host out of the browser's memory and out of
 * this component's props.
 */
/**
 * What one host answered, and which host-and-key it answered about.
 *
 * The pair is the point. A probe cannot be cancelled, so a reply can arrive after
 * the address or the credential has moved on - and an answer whose `for` is not
 * the form as it stands is not displayed at all, rather than being checked against
 * a ref that only the asking code updates.
 */
interface ProbeAnswer {
  for: string;
  runtimes: SandboxRuntime[] | null;
  failure: ReturnType<typeof submitFailure> | null;
}

export function ConnectionDialog({ editing, onOpenChange, onSubmit }: ConnectionDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("sandboxes.connection");
  const { secrets } = useSecrets();
  // Only asked for a new connection. An operator editing an existing row has
  // already decided which host it points at, and probing on their behalf would be
  // offering to change it.
  const { local, runtimes, storeCredential, probe } = useLocalSandboxService(editing === null);
  const [form, setForm] = useState<FormState>(() => initialState(editing, t("namePlaceholder")));
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [answer, setAnswer] = useState<ProbeAnswer | null>(null);
  const [failure, setFailure] = useState(NO_FAILURE);

  // Derived rather than written into state by an effect: what a service answered
  // is a default for a field nobody has touched, and an effect that filled the box
  // would refill it every time somebody cleared it to type another host. `touched`
  // is what separates "not filled in yet" from "deliberately empty".
  const baseUrl = form.urlTouched ? form.baseUrl : form.baseUrl || (local?.url ?? "");

  const address = baseUrl.trim();
  const secretId = form.secretId;
  // Which host-and-key an answer is about, and it is stored *with* the answer
  // rather than checked when one arrives. A probe cannot be cancelled, and a reply
  // about a host that is no longer in the box is the same defect whether it lost a
  // race with a second probe or simply landed after the address was edited - which
  // is what a "is this still current?" check written inside `ask` cannot see. Kept
  // as data, so an answer for anything but the form as it stands now is not an
  // answer this form displays: the field falls back to the catalogue's own list
  // until the host has been asked again.
  const identity = `${address}\u0000${secretId ?? ""}`;
  const allowed = answer !== null && answer.for === identity ? answer.runtimes : null;
  const refused = answer !== null && answer.for === identity ? answer.failure : null;
  const shown = refused ?? failure;

  // Which question is outstanding, so a slower earlier reply does not overwrite a
  // faster later one. This is the *other* half: `for` above stops an answer being
  // displayed for a host that is no longer in the box, and this stops one being
  // recorded over a newer host's. Neither covers both.
  const inFlight = useRef<string | null>(null);
  const ask = useCallback(async () => {
    const forWhom = `${address}\u0000${secretId ?? ""}`;
    inFlight.current = forWhom;
    setTesting(true);
    setFailure(NO_FAILURE);
    try {
      const policy = await probe(address, secretId);
      if (inFlight.current !== forWhom) return;
      setAnswer({ for: forWhom, runtimes: policy.runtimes, failure: null });
    } catch (error) {
      if (inFlight.current !== forWhom) return;
      setAnswer({ for: forWhom, runtimes: null, failure: submitFailure(error, FORM, tErrors) });
    } finally {
      if (inFlight.current === forWhom) setTesting(false);
    }
  }, [address, secretId, probe, tErrors]);

  /**
   * Ask, but only the address this deployment reported itself.
   *
   * The runtime list is what this deployment ships until a host has answered, and
   * a service can have been started with a different allowlist - which the field
   * marks, but only after somebody presses `Test`. So a form filled in and saved
   * without pressing it registered a default the first tool call refuses, and the
   * button that would have said so looked optional (#1039).
   *
   * **And a probe sends the vault credential to whatever address is in the box.**
   * `X-Sandbox-Token` on a sandbox host is root-equivalent - it starts containers
   * there - so asking automatically about a typed or pasted address means
   * disclosing that token to it before anybody decided to. Debouncing does not
   * make that safe; it only delays it. So the automatic ask is limited to the
   * address the backend itself found (`local.url`), which is this project's own
   * compose file, and every other host is asked when an operator presses the
   * button. Found by the review on #1040.
   */
  const knownAddress = local?.url ?? null;
  // The service this deployment found, with a token this deployment holds. The
  // backend accepts a probe with no key for its own compose addresses and only
  // those, so this is the same bound stated on the button.
  const askableWithLocalToken = local !== null && local.token_available && address === knownAddress;
  useEffect(() => {
    if (address !== knownAddress || !address) return;
    if (!secretId && !askableWithLocalToken) return;
    const timer = setTimeout(() => void ask(), 600);
    return () => clearTimeout(timer);
  }, [address, secretId, knownAddress, askableWithLocalToken, ask]);

  const usable = secrets.filter((secret) => secret.kind === "api_key");

  /**
   * Whether creating this connection will store this deployment's own token.
   *
   * Only where there is one to store, the kind that uses it, and nothing already
   * chosen - picking a key from the vault is a decision, and overriding it with
   * the local token would undo it.
   */
  const usesDeploymentToken =
    form.kind === "docker" && local?.token_available === true && form.secretId === null;

  async function submit(): Promise<void> {
    setSaving(true);
    setFailure(NO_FAILURE);
    try {
      // Before the connection, because the connection names it. A failure here is
      // reported the same way a refused form is, rather than leaving a row whose
      // credential does not exist.
      const secretId = usesDeploymentToken ? await storeCredential() : form.secretId;
      await onSubmit({
        name: form.name.trim(),
        kind: form.kind,
        // Daytona has an address of its own, so ours is deliberately cleared
        // rather than left holding whatever was typed before the kind changed.
        base_url: form.kind === "docker" ? baseUrl.trim() : null,
        secret_id: secretId,
        default_runtime: form.defaultRuntime.trim() || null,
        is_default: form.isDefault,
        is_active: form.isActive,
      });
      onOpenChange(false);
    } catch (error) {
      // Shown here rather than rethrown. The server refuses a duplicate name and
      // a shape it cannot use; both are about a field on this form, and a
      // rejection that escaped an onClick reached nobody at all.
      setFailure(submitFailure(error, FORM, tErrors));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      {/* Wider and two-up rather than one field per row down a page: with a
          paragraph under every input this dialog was 1150 pixels tall, which on a
          laptop is a form somebody scrolls to find the button of (#1039). Wide
          enough that `Container service - a sandboxd you run` fits its trigger,
          because a truncated kind is the one field nobody can guess. */}
      <DialogContent className={DIALOG_WIDE}>
        <DialogHeader>
          <DialogTitle>{editing ? t("editTitle") : t("addTitle")}</DialogTitle>
          <DialogDescription>{t("whereOrganizationAposS")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              htmlFor="connection-name"
              label={t("name")}
              description={t("whatAgentAuthorsWill")}
              error={shown.fields.name}
            >
              <Input
                id="connection-name"
                value={form.name}
                placeholder={t("namePlaceholder")}
                onChange={(event) => {
                  setForm({ ...form, name: event.target.value });
                  setFailure(NO_FAILURE);
                }}
              />
            </FormField>

            <div className="space-y-2">
              <Label htmlFor="connection-kind">{t("kind")}</Label>
              <Select
                value={form.kind}
                onValueChange={(kind) =>
                  setForm({ ...form, kind: kind as SandboxConnectionKind, secretId: null })
                }
              >
                <SelectTrigger id="connection-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="docker">
                    <span className="flex items-center gap-2">
                      <ConnectionKindIcon kind="docker" />
                      {t("kindDocker")}
                    </span>
                  </SelectItem>
                  <SelectItem value="daytona">
                    <span className="flex items-center gap-2">
                      <ConnectionKindIcon kind="daytona" />
                      {t("kindDaytona")}
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {form.kind === "docker" && (
            <div className="space-y-2">
              <FormField
                htmlFor="connection-url"
                label={t("address")}
                description={t("whereSandboxServiceAnswers")}
                error={shown.fields.base_url}
              >
                <Input
                  id="connection-url"
                  value={baseUrl}
                  placeholder="http://sandboxd:8080"
                  onChange={(event) => {
                    setForm({ ...form, baseUrl: event.target.value, urlTouched: true });
                    setFailure(NO_FAILURE);
                  }}
                />
              </FormField>
              {local?.url != null && (
                <p className="text-muted-foreground text-xs">
                  {local.registered_connection_id === null
                    ? t("localServiceFound", { url: local.url })
                    : t("localServiceAlreadyConnected", { url: local.url })}
                </p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="connection-secret">{t("credential")}</Label>
            <Select
              value={usable.find((secret) => secret.id === form.secretId)?.id ?? ""}
              onValueChange={(secretId) => setForm({ ...form, secretId })}
            >
              <SelectTrigger id="connection-secret">
                <SelectValue placeholder={t("pickFromVault")} />
              </SelectTrigger>
              <SelectContent>
                {usable.map((secret) => (
                  <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                    {/* Every API key in the vault is offered here, whatever it
                        is for, so its purpose is the only thing that says which
                        service a row's token belongs to. Most of them have no
                        brand mark - `sandboxd` and `daytona` included - and the
                        monogram is what keeps those from being a blank gap. */}
                    <ProviderRow
                      provider={secret.purpose ?? "custom"}
                      name={secret.name}
                      hint={secret.hint}
                    />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {form.kind === "docker" ? t("dockerTokenHint") : t("daytonaKeyHint")}
            </p>
            {/* The token is not something to go and find: `make sandbox-token`
                generated it into `backend/.env`, and that is the file the service
                was started from. So it is stored when the connection is created
                and nobody is asked to press a button first - and *at* creation
                rather than on open, or a dialog somebody opened and cancelled
                would leave a vault entry nobody asked for. */}
            {usesDeploymentToken && (
              <p className="text-muted-foreground text-xs">{t("willUseDeploymentToken")}</p>
            )}
            <InlineSecret
              kind="api_key"
              purpose={PURPOSE[form.kind]}
              suggestedName={t(SUGGESTED_NAME[form.kind])}
              onCreated={(secretId) => setForm({ ...form, secretId })}
            />
          </div>

          {form.kind === "docker" ? (
            <RuntimeField
              value={form.defaultRuntime}
              onChange={(defaultRuntime) => setForm({ ...form, defaultRuntime })}
              catalog={runtimes}
              allowed={allowed}
              // Nothing to ask with until there is an address and something to
              // authenticate with, and a button that answers "fill both in first"
              // is a button that wasted somebody's click. The deployment's own
              // token counts as something: adding the service `make dev` started
              // names no key until submission, which is the commonest path through
              // this dialog and had no way to test the host at all.
              onTest={address && (secretId || askableWithLocalToken) ? ask : null}
              testing={testing}
            />
          ) : (
            <div className="space-y-2">
              <Label htmlFor="connection-runtime">{t("defaultRuntime")}</Label>
              <Input
                id="connection-runtime"
                value={form.defaultRuntime}
                placeholder={t("serviceSOwn")}
                onChange={(event) => setForm({ ...form, defaultRuntime: event.target.value })}
              />
              <p className="text-muted-foreground text-xs">{t("daytonaSnapshotImageWhat")}</p>
            </div>
          )}

          <div className="flex items-center justify-between">
            <div>
              <Label htmlFor="connection-default">{t("useByDefault")}</Label>
              <p className="text-muted-foreground text-xs">{t("agentsNameNoConnection")}</p>
            </div>
            <Switch
              id="connection-default"
              checked={form.isDefault}
              onCheckedChange={(isDefault) => setForm({ ...form, isDefault })}
            />
          </div>

          {editing && (
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="connection-active">{t("switchedOn")}</Label>
                <p className="text-muted-foreground text-xs">{t("turningOffRefusesNew")}</p>
              </div>
              <Switch
                id="connection-active"
                checked={form.isActive}
                onCheckedChange={(isActive) => setForm({ ...form, isActive })}
              />
            </div>
          )}
        </div>

        {/* What could not be placed under an input - a refused permission, a
            vault write that failed, a server fault. A refusal that found its
            field is not also announced here. */}
        {shown.toast !== null && <p className="text-destructive text-sm">{shown.toast}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} disabled={saving || !isComplete(form, baseUrl)}>
            {editing ? t("save") : t("add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
