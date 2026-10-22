"use client";

import Link from "next/link";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { useCapabilityFieldCopy } from "@/components/agents/capability-field-copy";
import { SchemaForm } from "@/components/agents/schema-form";
import {
  Button,
  IconButton,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useSecrets } from "@/hooks";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import { useMirageBackends } from "@/hooks/use-mirage-backends";
import { usePermissions } from "@/hooks/use-permissions";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, JsonSchema } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { MirageBackend, MirageMountSpec } from "@/types/mirage";

/** Mirrors `MAX_MOUNTS` in `app/agents/capabilities/mirage/__init__.py`. */
const MAX_MOUNTS = 10;

/** The account choice that is not one of the organization's: each person's own. */
const PERSONAL = "__personal__";

/** The secret field an Entra app is stored under, for a Microsoft service. */
const ENTRA_FIELD = "app";

interface MirageSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  onToggleEnabled?: () => void;
  /** Whether the caller may edit the spec at all - see `CapabilityDetail`. */
  readOnly?: boolean;
  disabled?: boolean;
  configProblems?: readonly FieldProblem[];
}

/**
 * The virtual terminal's folders: which service each one reads, and as whom.
 *
 * A generated form cannot draw this. A mount's options depend on the service
 * picked beside them, and so does how it signs in - vault secrets field by field,
 * an Entra app, a Google account - so the service list and each one's form come
 * from the deployment, and only the shape of a folder row is written here. The
 * shell's own limits are the rest of the config schema, generated as always.
 */
export function MirageSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: MirageSectionProps) {
  const t = useTranslations("mirage");
  const backends = useMirageBackends();
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);
  const copyFor = useCapabilityFieldCopy(binding.id);

  if (!definition) return null;

  const mounts = Array.isArray(binding.config.mounts)
    ? (binding.config.mounts as MirageMountSpec[])
    : [];
  const setMounts = (next: MirageMountSpec[]) =>
    onChange({ ...binding, config: { ...binding.config, mounts: next } });
  const items = backends.data?.items ?? [];
  const firstUsable = items.find((entry) => entry.available);

  const controls = (
    <div className="space-y-4">
      {backends.isError && <p className="text-destructive text-xs">{t("backendsUnavailable")}</p>}
      {backends.data?.installed === false && (
        <p className="text-muted-foreground text-xs">{t("notInstalled")}</p>
      )}

      <div className="space-y-1.5">
        <Label>{t("folders")}</Label>
        <p className="text-muted-foreground text-xs">{t("foldersDetail")}</p>
      </div>

      {mounts.length > 0 && (
        <div className="divide-border divide-y">
          {mounts.map((mount, index) => (
            <MountRow
              // A folder's path is what the author edits, so it cannot key the row.
              key={index}
              index={index}
              mount={mount}
              backends={items}
              disabled={disabled}
              errors={mountErrors(configErrors, index)}
              onChange={(next) => setMounts(mounts.map((m, i) => (i === index ? next : m)))}
              onRemove={() => setMounts(mounts.filter((_, i) => i !== index))}
            />
          ))}
        </div>
      )}

      {configErrors.mounts && <p className="text-destructive text-xs">{configErrors.mounts}</p>}

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || firstUsable === undefined || mounts.length >= MAX_MOUNTS}
        onClick={() => firstUsable && setMounts([...mounts, newMount(firstUsable, mounts)])}
      >
        <Plus className="h-4 w-4" />
        {t("addFolder")}
      </Button>

      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutMounts(definition.config_schema)}
          value={binding.config}
          disabled={disabled}
          errors={configErrors}
          copyFor={copyFor}
          onChange={(config) => onChange({ ...binding, config })}
        />
      )}
    </div>
  );

  return (
    <CapabilityDetail
      binding={binding}
      definition={definition}
      onChange={onChange}
      onToggleEnabled={onToggleEnabled}
      readOnly={readOnly}
      disabled={disabled}
      configProblems={configProblems}
      settingsExtra={controls}
      // The folders and the generated fields above are the whole configuration.
      hideConfigForm
    />
  );
}

interface MountRowProps {
  index: number;
  mount: MirageMountSpec;
  backends: MirageBackend[];
  disabled?: boolean;
  errors: string[];
  onChange: (mount: MirageMountSpec) => void;
  onRemove: () => void;
}

function MountRow({ index, mount, backends, disabled, errors, onChange, onRemove }: MountRowProps) {
  const t = useTranslations("mirage");
  const id = `mirage-${index}`;
  const info = backends.find((entry) => entry.name === mount.backend);
  const writable = mount.mode === "write";

  /** Another service keeps the folder and drops what belonged to the last one. */
  const chooseBackend = (name: string) => {
    const next = backends.find((entry) => entry.name === name);
    // The select hands back only a name from this same list, so the lookup
    // cannot miss; the guard is the type checker's price for that.
    if (next)
      onChange({ path: mount.path, backend: name, mode: mount.mode, ...credentialFor(next) });
  };

  return (
    <div className="space-y-3 py-4 first:pt-0 last:pb-0">
      <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr_auto]">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-path`}>{t("folder")}</Label>
          <Input
            id={`${id}-path`}
            value={mount.path}
            disabled={disabled}
            // i18n-exempt: a folder path, the same in every language.
            placeholder="/drive/"
            onChange={(event) => onChange({ ...mount, path: event.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-backend`}>{t("service")}</Label>
          <Select
            value={info ? mount.backend : ""}
            disabled={disabled}
            onValueChange={chooseBackend}
          >
            <SelectTrigger id={`${id}-backend`}>
              <SelectValue placeholder={t("servicePlaceholder", { name: mount.backend })}>
                {info?.title}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {backends.map((entry) => (
                <SelectItem
                  key={entry.name}
                  value={entry.name}
                  disabled={!entry.available}
                  textValue={entry.title}
                >
                  <span className="flex flex-col gap-0.5">
                    <span>{entry.title}</span>
                    {entry.reason && (
                      <span className="text-muted-foreground text-xs">{entry.reason}</span>
                    )}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-end">
          <IconButton
            type="button"
            variant="ghost"
            aria-label={t("removeFolder", { folder: mount.path })}
            disabled={disabled}
            onClick={onRemove}
          >
            <Trash2 className="h-4 w-4" />
          </IconButton>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <Switch
            id={`${id}-write`}
            checked={writable}
            disabled={disabled}
            onCheckedChange={(on) => onChange({ ...mount, mode: on ? "write" : "read" })}
          />
          <Label htmlFor={`${id}-write`}>{t("writable")}</Label>
        </div>
        {writable && (
          <div className="flex items-center gap-2">
            <Switch
              id={`${id}-approve`}
              checked={mount.approve_writes !== false}
              disabled={disabled}
              onCheckedChange={(on) => onChange({ ...mount, approve_writes: on })}
            />
            <Label htmlFor={`${id}-approve`}>{t("approveWrites")}</Label>
          </div>
        )}
      </div>

      {info && (
        <Credentials id={id} info={info} mount={mount} disabled={disabled} onChange={onChange} />
      )}

      {info && Object.keys(info.options_schema.properties ?? {}).length > 0 && (
        <SchemaForm
          idPrefix={`${id}-options`}
          schema={info.options_schema as JsonSchema}
          value={mount.options ?? {}}
          disabled={disabled}
          onChange={(options) => onChange({ ...mount, options })}
        />
      )}

      {errors.map((error) => (
        <p key={error} className="text-destructive text-xs">
          {error}
        </p>
      ))}
    </div>
  );
}

interface CredentialsProps {
  id: string;
  info: MirageBackend;
  mount: MirageMountSpec;
  disabled?: boolean;
  onChange: (mount: MirageMountSpec) => void;
}

/** How the folder signs in: the shape is the service's, the choice the author's. */
function Credentials({ id, info, mount, disabled, onChange }: CredentialsProps) {
  if (info.credential === "none") return null;
  if (info.credential === "google") {
    return <AccountPicker id={id} mount={mount} disabled={disabled} onChange={onChange} />;
  }
  const fields = info.credential === "microsoft" ? [ENTRA_FIELD] : info.secret_fields;
  const kind = info.credential === "microsoft" ? "entra_app" : "api_key";
  const secrets = mount.secrets ?? {};
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.map((field) => (
        <SecretPicker
          key={field}
          id={`${id}-secret-${field}`}
          field={field}
          kind={kind}
          required={info.credential === "microsoft" || info.required_secrets.includes(field)}
          value={secrets[field]}
          disabled={disabled}
          onChange={(secretId) => {
            const { [field]: _dropped, ...rest } = secrets;
            onChange({
              ...mount,
              secrets: secretId === null ? rest : { ...rest, [field]: secretId },
            });
          }}
        />
      ))}
    </div>
  );
}

/** The picker's "none" choice; Radix refuses an empty string as an item's value. */
const NO_SECRET = "__none__";

interface SecretPickerProps {
  id: string;
  field: string;
  kind: "api_key" | "entra_app";
  required: boolean;
  value: string | undefined;
  disabled?: boolean;
  onChange: (secretId: string | null) => void;
}

function SecretPicker({ id, field, kind, required, value, disabled, onChange }: SecretPickerProps) {
  const t = useTranslations("mirage");
  const { secrets, isLoading } = useSecrets();
  const usable = secrets.filter((secret) => secret.kind === kind);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{kind === "entra_app" ? t("entraApp") : t("secretFor", { field })}</Label>
      <Select
        // Only a reference that resolves is handed over, so a deleted secret shows
        // the placeholder rather than a blank control.
        value={usable.some((secret) => secret.id === value) ? value : required ? "" : NO_SECRET}
        disabled={disabled || isLoading}
        onValueChange={(next) => onChange(next === NO_SECRET ? null : next)}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={t("chooseSecret")} />
        </SelectTrigger>
        <SelectContent>
          {!required && <SelectItem value={NO_SECRET}>{t("noSecret")}</SelectItem>}
          {usable.map((secret) => (
            <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
              {secret.name} <span className="text-muted-foreground">…{secret.hint}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!isLoading && usable.length === 0 && (
        <p className="text-muted-foreground text-xs">
          {t.rich("noSecrets", {
            link: (chunks) => (
              <Link href={ROUTES.VAULT} className="underline">
                {chunks}
              </Link>
            ),
          })}
        </p>
      )}
    </div>
  );
}

interface AccountPickerProps {
  id: string;
  mount: MirageMountSpec;
  disabled?: boolean;
  onChange: (mount: MirageMountSpec) => void;
}

/**
 * Whose Google account the folder reads: one the organization connected, or each
 * person's own - which a person connects on the vault page, not here.
 */
function AccountPicker({ id, mount, disabled, onChange }: AccountPickerProps) {
  const t = useTranslations("mirage");
  const { can } = usePermissions();
  const { accounts } = useConnectedAccounts("organization", {
    enabled: can(Perm.connectionsView),
  });
  const value =
    mount.account?.kind === "personal"
      ? PERSONAL
      : mount.account?.kind === "organization"
        ? mount.account.connection_id
        : "";
  return (
    <div className="space-y-1.5">
      <Label htmlFor={`${id}-account`}>{t("account")}</Label>
      <Select
        value={value}
        disabled={disabled}
        onValueChange={(next) =>
          onChange({
            ...mount,
            account:
              next === PERSONAL
                ? { kind: "personal" }
                : { kind: "organization", connection_id: next },
          })
        }
      >
        <SelectTrigger id={`${id}-account`}>
          <SelectValue placeholder={t("chooseAccount")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={PERSONAL}>{t("personalAccounts")}</SelectItem>
          {accounts.map((account) => (
            <SelectItem key={account.id} value={account.id}>
              {account.email}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">
        {t.rich(value === PERSONAL ? "personalAccountsDetail" : "organizationAccountsDetail", {
          link: (chunks) => (
            <Link href={ROUTES.VAULT} className="underline">
              {chunks}
            </Link>
          ),
        })}
      </p>
    </div>
  );
}

/** What a mount starts with on a service: its sign-in, empty. */
function credentialFor(
  info: MirageBackend,
): Pick<MirageMountSpec, "options" | "secrets" | "account"> {
  return {
    options: {},
    secrets: {},
    account: info.credential === "google" ? { kind: "personal" } : null,
  };
}

/** A new folder on the first service that can be mounted, under a name not yet taken. */
function newMount(info: MirageBackend, mounts: readonly MirageMountSpec[]): MirageMountSpec {
  const taken = new Set(mounts.map((mount) => mount.path));
  const base = info.name.replace(/[^a-z0-9._-]/g, "");
  let path = `/${base}/`;
  for (let n = 2; taken.has(path); n++) path = `/${base}-${n}/`;
  return { path, backend: info.name, mode: "read", ...credentialFor(info) };
}

/** The server's refusals for one folder, wherever in it they point. */
function mountErrors(errors: Readonly<Record<string, string>>, index: number): string[] {
  const own = `mounts.${index}`;
  return Object.entries(errors)
    .filter(([field]) => field === own || field.startsWith(`${own}.`))
    .map(([, message]) => message);
}

/** The schema without the folders, which the rows above draw. */
function withoutMounts(schema: JsonSchema): JsonSchema {
  const { mounts: _mounts, ...properties } = schema.properties ?? {};
  return { ...schema, properties, required: (schema.required ?? []).filter((n) => n !== "mounts") };
}
