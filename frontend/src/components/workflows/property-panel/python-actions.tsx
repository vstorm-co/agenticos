"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";

import { Button, Input, Label } from "@/components/ui";
import { JsonView } from "@/components/ui/json-view";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { useMcpToolSchema } from "@/components/workflows/pickers/mcp-tool-picker";
import { NativeSelect } from "@/components/ui/native-select";
import type { NodeCatalog, NodeDefinition } from "@/lib/workflows/types";
import { nodeCopyKey } from "@/lib/workflows/node-copy";

import { isPythonConfigInput, isRecord } from "./schema-model";

type Config = Record<string, unknown>;

function properties(schema: NodeDefinition["input_schema"]) {
  return Object.keys(isRecord(schema?.properties) ? schema.properties : {});
}

/** Only published, eligible versions produce callable snippets; obsolete bindings stay visible. */
function boundPythonActions(catalog: NodeCatalog, value: Config) {
  return Object.entries(value).map(([name, raw]) => {
    const binding = isRecord(raw) ? raw : {};
    const action = catalog.items.find(
      (def) =>
        def.python_callable && def.id === binding.type && def.version === (binding.version ?? 1),
    );
    const inputs = properties(action?.input_schema ?? null);
    const configFields = action?.config_schema?.properties;
    const overrides = Object.entries(isRecord(configFields) ? configFields : {})
      .filter(
        ([key, field]) =>
          isRecord(field) && isPythonConfigInput(field, key, action?.input_schema ?? null),
      )
      .map(([key]) => key);
    const parameters = [...inputs, ...overrides].map((field) => `${field}=...`);
    const required = action?.config_schema?.required;
    const defaults = isRecord(binding.config) ? binding.config : {};
    const requiredArgs = overrides.filter(
      (key) => Array.isArray(required) && required.includes(key) && !Object.hasOwn(defaults, key),
    );
    return {
      name,
      binding,
      action,
      overrides: overrides.filter((key) => !requiredArgs.includes(key)),
      requiredArgs,
      signature: `${name}(${parameters.join(", ")})`,
    };
  });
}

type BoundFunction = ReturnType<typeof boundPythonActions>[number];

/** A recorded tool's inner arguments, unlike the workflow action's generic arguments object. */
function McpArguments({ bound, option = false }: { bound: BoundFunction; option?: boolean }) {
  const t = useTranslations("workflows");
  const config = isRecord(bound.binding.config) ? bound.binding.config : {};
  const schema = useMcpToolSchema(
    typeof config.connection_id === "string" ? config.connection_id : null,
    typeof config.tool === "string" ? config.tool : null,
  );
  const fields = properties(schema);
  const requiredNames = schema?.required;
  const required = Array.isArray(requiredNames)
    ? fields.filter((key) => requiredNames.includes(key))
    : [];
  const keys = required.length ? required : fields;
  if (option) {
    const signature =
      keys.length && keys.length <= 8
        ? `${bound.name}(arguments={${keys.map((key) => `${JSON.stringify(key)}: ...`).join(", ")}})`
        : bound.signature;
    return <option value={signature}>{signature}</option>;
  }
  return (
    schema && (
      <NativeDisclosure>
        <summary className="cursor-pointer text-xs">{t("pythonToolArguments")}</summary>
        <JsonView value={schema} />
      </NativeDisclosure>
    )
  );
}

export function pythonCallOptions(catalog: NodeCatalog, value: Config) {
  return boundPythonActions(catalog, value)
    .filter((bound) => bound.action)
    .map((bound) =>
      bound.action?.id === "mcp.call" ? (
        <McpArguments key={bound.name} bound={bound} option />
      ) : (
        <option key={bound.name} value={bound.signature}>
          {bound.signature}
        </option>
      ),
    );
}

export type ActionEditorSelection = readonly [string | null, (alias: string | null) => void];

/** Bind a published action contract once. Its input values belong in Python, not the form. */
export function PythonActions({
  catalog,
  value,
  disabled,
  onChange,
  renderConfig,
  editingAction,
  schema,
}: {
  catalog: NodeCatalog;
  editingAction?: ActionEditorSelection;
  schema: Config;
  value: Config;
  disabled?: boolean;
  onChange: (value: Config) => void;
  renderConfig: (
    alias: string,
    definition: NodeDefinition,
    config: Config,
    change: (config: Config) => void,
  ) => ReactNode;
}) {
  const t = useTranslations("workflows");
  const [selection, setSelection] = useState("");
  const [alias, setAlias] = useState("");
  const ownSelection = useState<string | null>(null);
  const [editing, setEditing] = editingAction ?? ownSelection;
  const available = catalog.items.filter((action) => action.python_callable);
  const keyOf = (action: NodeDefinition) => `${action.id}@${action.version}`;
  const selected = available.find((action) => keyOf(action) === selection);
  const names = isRecord(schema.propertyNames) ? schema.propertyNames : {};
  const forbidden = isRecord(names.not) ? names.not.enum : null;
  const valid =
    /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(alias) &&
    !(Array.isArray(forbidden) && forbidden.includes(alias)) &&
    !Object.hasOwn(value, alias);

  function select(key: string) {
    setSelection(key);
    const base = nodeCopyKey(key.replace(/@\d+$/, ""));
    let candidate = base;
    for (let n = 2; Object.hasOwn(value, candidate); n++) candidate = `${base}_${n}`;
    setAlias(candidate);
  }

  return (
    <div className="space-y-3">
      <Label htmlFor="python-action-source">{t("pythonActions")}</Label>
      <p className="text-muted-foreground text-xs">{t("pythonActionsHint")}</p>
      <NativeSelect
        id="python-action-source"
        value={selection}
        disabled={
          disabled ||
          (typeof schema.maxProperties === "number" &&
            Object.keys(value).length >= schema.maxProperties)
        }
        onChange={(event) => select(event.target.value)}
      >
        <option value="">{t("pythonSelectAction")}</option>
        {available.map((action) => (
          <option key={keyOf(action)} value={keyOf(action)}>
            {action.name} · {keyOf(action)}
          </option>
        ))}
      </NativeSelect>
      {selected && (
        <div className="space-y-2">
          <Label htmlFor="python-action-name">{t("pythonFunctionName")}</Label>
          <Input
            id="python-action-name"
            value={alias}
            disabled={disabled}
            onChange={(event) => setAlias(event.target.value)}
          />
          {alias && !valid && <p className="text-destructive text-xs">{t("pythonInvalidName")}</p>}
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled || !valid}
            onClick={() => {
              onChange({
                ...value,
                [alias]: { type: selected.id, version: selected.version, config: {} },
              });
              setEditing(alias);
              setSelection("");
            }}
          >
            {t("pythonBindAction")}
          </Button>
        </div>
      )}
      {boundPythonActions(catalog, value).map((bound) => {
        const { name, binding, action, signature } = bound;
        const outputKeys = properties(action?.output_schema ?? null);
        return (
          <div key={name} className="space-y-2 rounded-md border p-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-action-header={name}
                aria-expanded={editing === name}
                onClick={() => setEditing(editing === name ? null : name)}
                className="min-w-0 flex-1 text-left"
              >
                <code className="break-all">{signature}</code>
                <span className="text-muted-foreground block text-xs">
                  {action?.name ?? t("pythonActionUnavailable")}
                </span>
              </button>
              <Button
                type="button"
                aria-label={t("pythonRemoveAction", { name })}
                variant="ghost"
                size="icon-sm"
                disabled={disabled}
                onClick={() => {
                  const next = { ...value };
                  delete next[name];
                  onChange(next);
                }}
              >
                <Trash2 />
              </Button>
            </div>
            {editing === name && action && (
              <>
                {bound.requiredArgs.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    {t("pythonRequiredConfigArgs", { fields: bound.requiredArgs.join(", ") })}
                  </p>
                )}
                {bound.overrides.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    {t("pythonOverrideFields", { fields: bound.overrides.join(", ") })}
                  </p>
                )}
                {outputKeys.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    {t("pythonResultFields", { fields: outputKeys.join(", ") })}
                  </p>
                )}
                {action.id === "mcp.call" && <McpArguments bound={bound} />}
                {action.config_schema &&
                  renderConfig(
                    name,
                    action,
                    isRecord(binding.config) ? binding.config : {},
                    (config) =>
                      onChange({
                        ...value,
                        [name]: { ...binding, config },
                      }),
                  )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
