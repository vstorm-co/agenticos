"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronRight, ShieldAlert } from "lucide-react";

import { SchemaForm } from "@/components/agents/schema-form";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import { useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { cn, getErrorMessage } from "@/lib/utils";
import type {
  ApprovalMode,
  CapabilityBindingSpec,
  CapabilityCatalogEntry,
  CapabilityTool,
  CapabilityToolContract,
  JsonSchema,
  ToolOverride,
  ToolParameterSchema,
} from "@/types/agents";
import { secretIsRequired } from "@/types/secrets";
import type { Secret, SecretRequirement } from "@/types/secrets";
import { useTranslations } from "next-intl";

interface CapabilitySettingsProps {
  catalog: CapabilityCatalogEntry[];
  selected: CapabilityBindingSpec[];
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

const APPROVAL_OPTIONS: { value: ApprovalMode; label: string }[] = [
  { value: "default", label: "Follow the capability" },
  { value: "required", label: "Always ask" },
  { value: "never", label: "Never ask" },
];

/** What approval comes out to once every rule has been applied: ask, or don't. */
type ResolvedApproval = "required" | "never";

/** The two halves of a tool's description the model reads; both are overridable. */
type ToolTextField = "name" | "description";

/**
 * What a tool may be called.
 *
 * The model emits this string verbatim to call the tool, so it is an
 * identifier, not a label: a space or a dash produces a call nothing answers.
 */
const TOOL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Why this name will not do, or null when it will. Empty is not a name. */
export function toolNameError(name: string): string | null {
  if (name.length === 0) return "The model calls the tool by this name, so it cannot be blank.";
  if (!TOOL_NAME_PATTERN.test(name)) {
    return "Letters, digits and underscores only - the model calls this name verbatim.";
  }
  return null;
}

/** What the chosen mode means for *this* capability, in one line. */
export function approvalHint(mode: ApprovalMode, sideEffecting: boolean): string {
  if (mode === "required") {
    return "A person approves every call before it runs.";
  }
  if (mode === "never") {
    return sideEffecting
      ? "The agent acts unattended. Only for actions your organization has decided are safe."
      : "No approval, which is what this capability would do anyway.";
  }
  return sideEffecting
    ? "Held for approval, because this capability changes something outside the agent."
    : "Runs without approval, because this capability only reads.";
}

/**
 * Approval for one tool, most specific rule first: the tool's own override, then
 * the capability's mode, then what `side_effecting` decides.
 *
 * This is the frontend's copy of a rule the runtime also applies. It exists so
 * the Builder can *say* what a setting will do rather than describe the rule and
 * leave the reader to run it in their head - which is where per-tool approval
 * would otherwise become a thing nobody dares touch.
 */
export function resolveToolApproval(
  binding: CapabilityBindingSpec,
  toolId: string,
  sideEffecting: boolean,
): ResolvedApproval {
  return overrideFor(binding, toolId) ?? resolveCapabilityApproval(binding.approval, sideEffecting);
}

/** What a capability's own mode comes out to, `default` included. */
function resolveCapabilityApproval(mode: ApprovalMode, sideEffecting: boolean): ResolvedApproval {
  if (mode !== "default") return mode;
  return sideEffecting ? "required" : "never";
}

/**
 * Per-capability configuration for the capabilities an agent has switched on.
 *
 * Every bound capability appears, because every one has at least an approval
 * mode to set. This was filtered to capabilities that were configurable *or*
 * side-effecting, and the approval control rendered only for the side-effecting
 * ones - so with the current builtin set, where none of them are, it never
 * rendered at all.
 *
 * Worse, that hid the case worth reaching for. The backend honours `required`
 * on *any* capability, so "this only reads, but in my organization somebody
 * approves it anyway" is a real decision, and there was no way to express it.
 *
 * `side_effecting` still decides what *default* resolves to. It no longer
 * decides whether you may see the question.
 */
export function CapabilitySettings({
  catalog,
  selected,
  onChange,
  disabled,
}: CapabilitySettingsProps) {
  const configurable = selected
    .filter((binding) => binding.enabled)
    .map((binding) => ({
      binding,
      definition: catalog.find((entry) => entry.id === binding.id),
    }))
    .filter(
      (entry): entry is { binding: CapabilityBindingSpec; definition: CapabilityCatalogEntry } =>
        entry.definition !== undefined,
    );

  if (configurable.length === 0) return null;

  return (
    <div className="space-y-3">
      {configurable.map(({ binding, definition }) => (
        <CapabilityDetail
          key={binding.id}
          binding={binding}
          definition={definition}
          onChange={onChange}
          disabled={disabled}
        />
      ))}
    </div>
  );
}

interface CapabilityDetailProps {
  binding: CapabilityBindingSpec;
  definition: CapabilityCatalogEntry;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
  /**
   * Suppress the generated configuration form.
   *
   * For a capability whose configuration is a decision rather than a set of
   * fields - the workspace, where the choice of backend and of who shares it
   * are presented as what they are and one of them carries a warning a schema
   * cannot express. Everything else here (the secret, approval, tool text) is
   * the same for every capability and is not worth a second implementation.
   */
  hideConfigForm?: boolean;
}

/**
 * Everything one capability lets an agent decide.
 *
 * Its own component because the Builder shows exactly one at a time now - the
 * capability you are looking at, beside the list you picked it from. Stacking
 * every enabled one below a grid is what made these settings hard to find.
 */
export function CapabilityDetail({
  binding,
  definition,
  onChange,
  disabled,
  hideConfigForm,
}: CapabilityDetailProps) {
  const t = useTranslations("agents");
  return (
    // Grouped and named, so the tool rows below are read as belonging to
    // this capability rather than to the page.
    <Card role="group" aria-label={definition.name}>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{definition.name}</span>
          <span className="text-muted-foreground font-mono text-xs">{definition.id}</span>
          {definition.side_effecting && (
            <Badge variant="outline" className="gap-1">
              <ShieldAlert className="h-3 w-3" />
              acts on the outside world
            </Badge>
          )}
        </div>

        <p className="text-muted-foreground text-sm">{definition.description}</p>

        {definition.config_schema && !hideConfigForm && (
          <SchemaForm
            idPrefix={binding.id}
            schema={definition.config_schema}
            value={binding.config}
            disabled={disabled}
            onChange={(config) => onChange({ ...binding, config })}
          />
        )}

        {/* Only when *this* configuration needs one. A capability offering a
            free provider and a paid one declares the requirement once and
            names the configurations it applies to; asking for a key the server
            will not demand is as wrong as not asking for one it will. */}
        {definition.requires_secret !== null &&
          secretIsRequired(definition.requires_secret, binding.config) && (
            <SecretField
              binding={binding}
              requirement={definition.requires_secret}
              onChange={onChange}
              disabled={disabled}
            />
          )}

        {definition.requires_secret === null && binding.secret_id !== null && (
          <StaleSecretNotice binding={binding} onChange={onChange} disabled={disabled} />
        )}

        <div className="space-y-2">
          <Label htmlFor={`${binding.id}-approval`}>{t("humanApproval")}</Label>
          <Select
            value={binding.approval}
            disabled={disabled}
            onValueChange={(approval) =>
              onChange({ ...binding, approval: approval as ApprovalMode })
            }
          >
            <SelectTrigger id={`${binding.id}-approval`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {APPROVAL_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            {approvalHint(binding.approval, definition.side_effecting)}
            {definition.tools.length > 0 &&
              " Every tool below follows this until you answer for it separately."}
          </p>
        </div>

        {definition.tools.length > 0 && (
          <ToolList
            binding={binding}
            tools={definition.tools}
            contracts={definition.contracts}
            sideEffecting={definition.side_effecting}
            onChange={onChange}
            disabled={disabled}
          />
        )}

        {definition.config_schema && <SchemaPreview schema={definition.config_schema} />}
      </CardContent>
    </Card>
  );
}

/**
 * The configuration schema as the server states it.
 *
 * The form above is generated from this, so a control that looks wrong is
 * either a schema saying something unexpected or a form failing to render it -
 * and telling those apart without the source is guesswork.
 */
function SchemaPreview({ schema }: { schema: JsonSchema }) {
  return (
    <details className="group">
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1.5 text-xs">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        Configuration schema
      </summary>
      <pre className="text-muted-foreground bg-muted/50 mt-1.5 max-h-64 overflow-auto rounded-md p-3 text-xs">
        {JSON.stringify(schema, null, 2)}
      </pre>
    </details>
  );
}

/**
 * Why the secret a binding names will not satisfy the capability, or null when
 * it does.
 *
 * The three refusals `_secret_problems` produces about a *chosen* secret, said
 * where the choice is made: nothing selected, a reference this organization does
 * not have, and a secret of the wrong shape. Publishing says the same things an
 * hour later, in a list beside everything else wrong with the agent - and the
 * first of the three is the one an author reaches by doing nothing at all, which
 * is the worst possible way to find out.
 *
 * `secrets` must be the vault as actually read. An empty list because the
 * request was refused says nothing about what the organization holds, so a
 * caller that cannot read the vault must not ask this.
 */
export function secretProblem(
  requirement: SecretRequirement,
  secretId: string | null,
  secrets: readonly Secret[],
): string | null {
  if (secretId === null) {
    return `No secret selected. This capability needs one of kind ${requirement.kind}, and the agent cannot be published until it has one.`;
  }
  const secret = secrets.find((candidate) => candidate.id === secretId);
  if (secret === undefined) {
    return "The secret selected here is not in this organization's vault - it was deleted, or the spec was written against another organization. Publishing refuses it.";
  }
  if (secret.kind !== requirement.kind) {
    return `"${secret.name}" is of kind ${secret.kind}; this capability needs ${requirement.kind}. Publishing refuses it.`;
  }
  return null;
}

interface SecretFieldProps {
  binding: CapabilityBindingSpec;
  requirement: SecretRequirement;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * What the key chosen here would be for - "tavily", "brave" - when the binding
 * has said, and null when the requirement is unconditional and no field names a
 * service.
 *
 * It is the same answer `InlineSecret` stores under `purpose`, read back: the
 * conditional field *is* the service, so a requirement gated on `method` needs a
 * key for whichever method was picked.
 */
function purposeOf(binding: CapabilityBindingSpec, requirement: SecretRequirement): string | null {
  const field = requirement.required_when?.field;
  const chosen = field === undefined ? undefined : binding.config[field];
  return typeof chosen === "string" && chosen !== "" ? chosen : null;
}

/**
 * Whether a stored key belongs in the list for this slot.
 *
 * Kind alone is too wide: eleven `api_key` rows are eleven indistinguishable
 * options, and picking the OpenAI one for a Tavily search is a run that fails
 * with an authentication error nobody will trace back to this select.
 *
 * Purpose alone is too narrow, for two reasons that are not going away. Every
 * key stored before purposes existed reads as `custom`, and so does every key
 * for a service this deployment does not name - filtering those out would hide
 * a Tavily key that works. And the currently bound secret always stays offered:
 * a selection vanishing from its own control, on a spec that was saved and is
 * still valid, looks like data loss whatever the reason.
 */
function fitsPurpose(secret: Secret, purpose: string | null, selectedId: string | null): boolean {
  const declared = secret.purpose ?? "custom";
  return (
    purpose === null || declared === purpose || declared === "custom" || secret.id === selectedId
  );
}

/**
 * Which of the organization's secrets a capability that declares one is to use.
 *
 * It reads the vault itself rather than taking it as a prop, which is the
 * exception on this surface and deliberate. No builtin declares a secret, so a
 * `secrets` prop would make every capability card, and the Builder around them,
 * carry a request for a collection nothing on screen can use. And `GET /secrets`
 * is gated on `connections:manage` - which a member editing their own agent does
 * not have - so it is a request this page cannot assume succeeds; mounting it
 * only where a secret is actually required keeps the refusal where somebody can
 * be told what it means.
 *
 * Only secrets of the declared kind are offered. Offering an AWS credential
 * where an API key is required is offering a publish failure, and one the reader
 * would not connect to this control by the time they saw it.
 *
 * There is no option that clears the choice. Unset is a state - it is *the*
 * state that blocks publishing - but it is reached by not having chosen, never
 * by choosing, so offering it would be offering a way to break the agent.
 */
function SecretField({ binding, requirement, onChange, disabled }: SecretFieldProps) {
  const t = useTranslations("agents");
  const { secrets, isLoading, listError } = useSecrets();
  const fieldId = `${binding.id}-secret`;
  const errorId = `${fieldId}-error`;
  const purpose = purposeOf(binding, requirement);
  const usable = secrets.filter(
    (secret) => secret.kind === requirement.kind && fitsPurpose(secret, purpose, binding.secret_id),
  );
  const state = vaultState(isLoading, listError, usable.length);
  // Having selected nothing is a fact about the spec, so it is said whatever the
  // vault did. Whether a *selected* secret is missing or the wrong shape is a
  // claim about the organization's vault, and mid-flight or after a refusal `[]`
  // is what a full vault also looks like - a stored secret would otherwise read
  // as deleted on every load.
  const vaultWasRead = state === "ready" || state === "empty";
  const problem =
    binding.secret_id === null || vaultWasRead
      ? secretProblem(requirement, binding.secret_id, secrets)
      : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor={fieldId}>{t("secret")}</Label>
        <span className="text-muted-foreground font-mono text-xs">{requirement.kind}</span>
      </div>

      <Select
        // Only a reference that resolves to an offered secret is handed over:
        // Radix renders nothing at all for a value no item matches, so a
        // deleted, wrong-kind or unreadable reference would leave the control
        // blank and silent. Falling back to the placeholder puts the state into
        // words, and the line below says which state it is.
        value={usable.find((secret) => secret.id === binding.secret_id)?.id ?? ""}
        disabled={disabled || state !== "ready"}
        onValueChange={(secretId) => onChange({ ...binding, secret_id: secretId })}
      >
        <SelectTrigger
          id={fieldId}
          aria-invalid={problem !== null}
          aria-describedby={problem === null ? undefined : errorId}
        >
          <SelectValue placeholder={placeholderFor(state, requirement)} />
        </SelectTrigger>
        <SelectContent>
          {usable.map((secret) => (
            <SelectItem key={secret.id} value={secret.id}>
              {secret.name} <span className="font-mono">····{secret.hint}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <p className="text-muted-foreground text-xs">{requirement.description}</p>

      {state === "unreadable" && (
        <p className="text-destructive text-xs">
          The vault could not be read, so nothing can be chosen here - which says nothing about what
          your organization has stored. Listing secrets needs the permission that manages
          connections. {getErrorMessage(listError)}
        </p>
      )}

      {problem !== null && (
        <p id={errorId} className="text-destructive text-xs">
          {problem}
        </p>
      )}

      {/*
        The way forward for whoever has no suitable secret yet - which is
        everyone, the first time a capability of their own asks for one. Adding
        it here rather than sending them to the vault: the four-step round trip
        (open the vault, add the key, come back, re-pick the capability) is the
        one this control existed to demand, and the form has already worked out
        what shape of key is needed.
      */}
      {(state === "empty" || state === "ready") && requirement.kind === "api_key" && (
        <InlineSecret
          kind="api_key"
          // The chosen method *is* the service the key is for - "tavily",
          // "brave". Recording it is what lets the select above offer only the
          // right keys next time instead of every API key in the vault.
          purpose={purpose ?? "custom"}
          suggestedName={secretNameFor(binding.id)}
          helpUrl={SECRET_HELP[binding.id]}
          disabled={disabled}
          onCreated={(secretId) => onChange({ ...binding, secret_id: secretId })}
        />
      )}

      {state === "empty" && requirement.kind !== "api_key" && (
        <p className="text-muted-foreground text-xs">
          <Link href={ROUTES.VAULT} className="underline">
            Store one in the vault
          </Link>{" "}
          and it appears here - this shape has several fields, so it is filled in there. The value
          stays in the vault; an agent records which secret to use, never the secret.
        </p>
      )}
    </div>
  );
}

/**
 * What the vault is doing, as far as this control is concerned.
 *
 * Kept as one value because the three that are not `ready` differ in what may be
 * *said*, not only in what may be picked: "no API key stored" is a claim about
 * the organization, and a refused or unfinished request has not earned it.
 */
type VaultState = "loading" | "unreadable" | "empty" | "ready";

/**
 * Where to get a key, for the capabilities whose answer is a specific page.
 *
 * Only where it is unambiguous. A generic "search the web for your provider's
 * dashboard" link is worse than none: it looks like help and costs a click to
 * find out it is not.
 */
const SECRET_HELP: Record<string, string | undefined> = {
  web_research: "https://tavily.com",
};

/** A name somebody would have typed anyway, so the field starts filled in. */
function secretNameFor(capabilityId: string): string {
  return capabilityId
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function vaultState(isLoading: boolean, listError: Error | null, usableCount: number): VaultState {
  if (isLoading) return "loading";
  if (listError !== null) return "unreadable";
  return usableCount === 0 ? "empty" : "ready";
}

/** What the trigger says while nothing is chosen, which is not the same in each state. */
function placeholderFor(state: VaultState, requirement: SecretRequirement): string {
  switch (state) {
    case "loading":
      return "Reading the vault…";
    case "unreadable":
      return "The vault could not be read";
    case "empty":
      return `No ${requirement.kind} secret in the vault`;
    case "ready":
      return "Choose a secret";
  }
}

interface StaleSecretNoticeProps {
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * A secret named on a capability that consumes none.
 *
 * The fourth thing publishing refuses, and the only one of the four nobody would
 * ever notice: the binding reads as configured and the value is never read. It
 * arrives when a capability drops its requirement while an agent still names a
 * secret for it - and with no picker rendered for such a capability, there would
 * be nothing on this page able to undo it.
 */
function StaleSecretNotice({ binding, onChange, disabled }: StaleSecretNoticeProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
      <p className="text-destructive text-xs">
        This capability uses no secret, so the one selected for it would be stored and never read.
        Publishing refuses it.
      </p>
      <Button
        variant="ghost"
        size="sm"
        disabled={disabled}
        onClick={() => onChange({ ...binding, secret_id: null })}
      >
        Clear secret
      </Button>
    </div>
  );
}

interface ToolListProps {
  binding: CapabilityBindingSpec;
  tools: CapabilityTool[];
  contracts: CapabilityToolContract[];
  sideEffecting: boolean;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

/**
 * The tools of one capability, each with its own name, description and answer
 * to the approval question.
 *
 * The capability's own control above stays the way to set eight tools at once;
 * this list is for the one that differs. Clearing the overrides is offered
 * because the alternative is walking back through every row to find which of
 * them stopped following it.
 */
function ToolList({ binding, tools, contracts, sideEffecting, onChange, disabled }: ToolListProps) {
  const t = useTranslations("agents");
  const changed = tools.filter((tool) => isToolOverridden(binding, tool.id));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          {t("tools")}
        </p>
        {changed.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={() => onChange({ ...binding, tool_approval: {}, tool_overrides: {} })}
          >
            {changed.length === 1 ? "Clear 1 override" : `Clear ${changed.length} overrides`}
          </Button>
        )}
      </div>

      <p className="text-muted-foreground text-xs">
        A tool&apos;s name and description are the prompt the model reads before it decides to call
        it, so both steer it: <span className="font-mono">{t("searchRefundPolicy")}</span> is
        reached for on questions <span className="font-mono">{t("searchDocuments")}</span> is passed
        over for. Edits here apply to this agent alone.
      </p>

      <ul className="divide-y rounded-md border">
        {tools.map((tool) => (
          <ToolRow
            key={tool.id}
            binding={binding}
            tool={tool}
            contract={contracts.find((entry) => entry.tool_id === tool.id)}
            sideEffecting={sideEffecting}
            onChange={onChange}
            disabled={disabled}
          />
        ))}
      </ul>
    </div>
  );
}

interface ToolRowProps {
  binding: CapabilityBindingSpec;
  tool: CapabilityTool;
  /** What the model is really told. Absent only if the catalog could not read it. */
  contract?: CapabilityToolContract;
  sideEffecting: boolean;
  onChange: (binding: CapabilityBindingSpec) => void;
  disabled?: boolean;
}

function ToolRow({ binding, tool, contract, sideEffecting, onChange, disabled }: ToolRowProps) {
  const t = useTranslations("agents");
  const fieldId = (suffix: string) => `${binding.id}-tool-${tool.id}-${suffix}`;
  const approval = overrideFor(binding, tool.id);
  const name = effectiveText(binding, tool, "name");
  const nameError = toolNameError(name);
  const changed = isToolOverridden(binding, tool.id);

  const edit = (field: ToolTextField, value: string) =>
    onChange(withToolOverride(binding, tool.id, field, value));

  /** Offered only where there is something to go back from. */
  const resetFor = (field: ToolTextField, label: string) =>
    overriddenText(binding, tool.id, field)
      ? { label, onClick: () => onChange(withoutToolOverride(binding, tool.id, field)) }
      : undefined;

  return (
    <li
      // The id, not the name: it is what the spec keys both per-tool maps on,
      // it is what a backend validation error names, and it is the one string
      // on this row that renaming the tool does not move.
      aria-label={tool.id}
      className={cn(
        "space-y-3 p-3",
        // A page where every row looks the same is a page where nobody notices
        // the row somebody changed.
        changed && "border-brand bg-brand/5 border-l-2",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground font-mono text-xs">{tool.id}</span>
        {changed && <Badge variant="secondary">{t("overridden")}</Badge>}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <ToolField
          htmlFor={fieldId("name")}
          label={t("name2")}
          reset={resetFor("name", "Reset name")}
          error={nameError}
          disabled={disabled}
        >
          <Input
            id={fieldId("name")}
            value={name}
            disabled={disabled}
            spellCheck={false}
            aria-invalid={nameError !== null}
            aria-describedby={nameError === null ? undefined : `${fieldId("name")}-error`}
            onChange={(event) => edit("name", event.target.value)}
            className="font-mono text-sm"
          />
        </ToolField>

        <ToolField htmlFor={fieldId("approval")} label={t("approval")} disabled={disabled}>
          <Select
            value={approval ?? "default"}
            disabled={disabled}
            onValueChange={(mode) =>
              onChange(withToolApproval(binding, tool.id, mode as ApprovalMode))
            }
          >
            <SelectTrigger id={fieldId("approval")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="default">
                {resolveCapabilityApproval(binding.approval, sideEffecting) === "required"
                  ? "Follow the capability - always ask"
                  : "Follow the capability - never ask"}
              </SelectItem>
              {APPROVAL_OPTIONS.filter((option) => option.value !== "default").map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </ToolField>
      </div>

      <ToolField
        htmlFor={fieldId("description")}
        label={t("descriptionModelReads")}
        reset={resetFor("description", "Reset description")}
        disabled={disabled}
      >
        {/* One field, holding the whole text. An override replaces everything
            the model is told about this tool, so an editor showing only the
            summary sentence was an editor for a value that does not exist -
            editing "the short one" silently deleted the rest. The default
            shown is the full contract, which is exactly what an untouched
            binding sends. */}
        <Textarea
          id={fieldId("description")}
          value={
            binding.tool_overrides[tool.id]?.description ??
            contract?.description ??
            tool.description
          }
          disabled={disabled}
          rows={6}
          className="text-xs leading-relaxed"
          onChange={(event) => edit("description", event.target.value)}
        />
      </ToolField>

      {contract && <ToolContract contract={contract} />}
    </li>
  );
}

/**
 * The half of the contract a spec cannot rewrite.
 *
 * The description lives in the editable field above - the whole of it, since
 * an override replaces the whole of it. What remains here are the arguments,
 * read-only on purpose: they come from the function signature, and a spec
 * cannot rename them.
 */
function ToolContract({ contract }: { contract: CapabilityToolContract }) {
  const t = useTranslations("agents");
  const properties = contract.parameters.properties ?? {};
  const names = Object.keys(properties);
  const required = new Set(contract.parameters.required ?? []);

  return (
    <div className="space-y-1.5">
      {names.length > 0 && (
        <details className="group">
          <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1.5 text-xs">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Arguments ({names.length})
          </summary>
          <ul className="mt-1.5 space-y-1">
            {names.map((name) => (
              <li key={name} className="flex items-baseline gap-2 text-xs">
                <span className="text-foreground font-mono">{name}</span>
                <span className="text-muted-foreground font-mono">
                  {jsonSchemaType(properties[name])}
                </span>
                {required.has(name) && (
                  <span className="text-muted-foreground">{t("required")}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** A JSON Schema node as one readable word, for a list that has no room for more. */
export function jsonSchemaType(node: ToolParameterSchema | undefined): string {
  if (!node) return "unknown";
  if (typeof node.type === "string") {
    if (node.type === "array" && node.items) return `array<${jsonSchemaType(node.items)}>`;
    return node.type;
  }
  if (Array.isArray(node.anyOf)) {
    // `T | null` is how an optional argument arrives; naming the null half adds
    // nothing a reader of "required" does not already have.
    const named = node.anyOf.map(jsonSchemaType).filter((name) => name !== "null");
    return named.join(" | ") || "null";
  }
  if (node.$ref) return node.$ref.split("/").pop() ?? "object";
  if (node.enum) return node.enum.map(String).join(" | ");
  return "object";
}

interface ToolFieldProps {
  htmlFor: string;
  label: string;
  /** The way back to the value the capability declared in code - absent when it is that. */
  reset?: { label: string; onClick: () => void };
  error?: string | null;
  disabled?: boolean;
  children: ReactNode;
}

/**
 * One labelled control in a tool row, with the way back beside its label.
 *
 * The reset button is the field's override marker as much as its remedy: an
 * edit that can only be undone by retyping the original is an edit nobody
 * makes, because the original is exactly what the person no longer knows.
 */
function ToolField({ htmlFor, label, reset, error, disabled, children }: ToolFieldProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex min-h-8 items-center justify-between gap-2">
        <Label htmlFor={htmlFor}>{label}</Label>
        {reset && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            disabled={disabled}
            onClick={reset.onClick}
          >
            {reset.label}
          </Button>
        )}
      </div>
      {children}
      {error && (
        <p id={`${htmlFor}-error`} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * The approval override stored for a tool, or undefined when it follows the
 * capability.
 *
 * A stored `"default"` is the same statement as a missing key - a spec written
 * by hand or exported from an older deployment can contain either - so both
 * read as "no override" and neither gets marked as one.
 */
function overrideFor(binding: CapabilityBindingSpec, toolId: string): ResolvedApproval | undefined {
  const mode = binding.tool_approval[toolId];
  return mode === undefined || mode === "default" ? undefined : mode;
}

/** Whether this agent replaced one half of what the model is told about a tool. */
function overriddenText(
  binding: CapabilityBindingSpec,
  toolId: string,
  field: ToolTextField,
): boolean {
  return binding.tool_overrides[toolId]?.[field] !== undefined;
}

/**
 * What the model will be given: this binding's edit if it has one, otherwise
 * the value the catalog resolved.
 *
 * The two agree for an override the API has already seen. Reading the binding
 * first is what keeps an unsaved edit on screen, and what leaves a reverted
 * field showing the value the capability declares rather than the one it was
 * just put back from.
 */
function effectiveText(
  binding: CapabilityBindingSpec,
  tool: CapabilityTool,
  field: ToolTextField,
): string {
  return binding.tool_overrides[tool.id]?.[field] ?? tool[field];
}

/** Whether anything on this row differs from what the capability declared. */
function isToolOverridden(binding: CapabilityBindingSpec, toolId: string): boolean {
  return (
    overrideFor(binding, toolId) !== undefined ||
    overriddenText(binding, toolId, "name") ||
    overriddenText(binding, toolId, "description")
  );
}

/** Following the capability is stored as the absence of a key, not as a value. */
function withToolApproval(
  binding: CapabilityBindingSpec,
  toolId: string,
  mode: ApprovalMode,
): CapabilityBindingSpec {
  const tool_approval = { ...binding.tool_approval };
  if (mode === "default") {
    delete tool_approval[toolId];
  } else {
    tool_approval[toolId] = mode;
  }
  return { ...binding, tool_approval };
}

/**
 * Store what was typed, even when it happens to match the code default.
 *
 * Treating "you typed the current value back" as a revert would delete an
 * override the moment somebody retyped the name they had already set - the
 * catalog hands back the *effective* name, so the two are the same string.
 * Reverting is the button, not a coincidence.
 */
function withToolOverride(
  binding: CapabilityBindingSpec,
  toolId: string,
  field: ToolTextField,
  value: string,
): CapabilityBindingSpec {
  return {
    ...binding,
    tool_overrides: {
      ...binding.tool_overrides,
      [toolId]: { ...binding.tool_overrides[toolId], [field]: value },
    },
  };
}

/** Drop one override, and the tool's entry with it once nothing is left in it. */
function withoutToolOverride(
  binding: CapabilityBindingSpec,
  toolId: string,
  field: ToolTextField,
): CapabilityBindingSpec {
  const existing = binding.tool_overrides[toolId];
  /* v8 ignore next -- `bindings` is keyed by the ids this maps over */
  if (existing === undefined) return binding;

  const remaining: ToolOverride = { ...existing };
  delete remaining[field];

  const tool_overrides = { ...binding.tool_overrides };
  // An emptied entry is not the same as no entry to `isDirty`, which compares
  // the spec on screen against the one the server holds - leaving `{}` behind
  // would mark the draft unsaved for as long as it stayed open.
  if (remaining.name === undefined && remaining.description === undefined) {
    delete tool_overrides[toolId];
  } else {
    tool_overrides[toolId] = remaining;
  }
  return { ...binding, tool_overrides };
}
