"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { AnswerFormatForm } from "@/components/agents/answer-format-form";
import { SchemaForm } from "@/components/agents/schema-form";
import { MemberPicker } from "@/components/orgs/member-picker";
import {
  AgentVersionPicker,
  ChannelBotPicker,
  SandboxConnectionPicker,
  CollectionPicker,
  SecretPicker,
  TableColumnPicker,
  type AgentVersionRef,
} from "@/components/workflows/pickers";
import { useKnowledgeBases, useMembers } from "@/hooks";
import { useOrgStore } from "@/stores";
import {
  bindingFieldPath,
  type Binding,
  type NodeCatalog,
  type NodeDefinition,
  type NodeInstance,
  type TableIORef,
  type Uuid,
  type WorkflowGraph,
} from "@/lib/workflows/types";

import {
  CHAT_TRIGGER,
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  WEBHOOK_TRIGGER,
} from "@/lib/workflows/triggers";

import { BindingField } from "./binding-field";
import { InputFieldsForm } from "./input-fields-form";
import { ScheduleTriggerForm } from "./schedule-trigger-form";
import { applyRebase, rebaseClear, rebaseRemove, rebaseSwap } from "./bindings";
import {
  classify,
  defsOf,
  isBindable,
  isRecord,
  labelOf,
  ownTitle,
  objectFields,
  resourceKind,
  secretKind,
  singleFieldSchema,
  type Defs,
  type ResourceKind,
  type Schema,
  type UnionShape,
} from "./schema-model";

/**
 * What a trigger with nothing to configure says instead of "no settings": how a
 * run begins through it, and what it hands the steps after it.
 */
const TRIGGER_HINTS: Record<string, string> = {
  [CHAT_TRIGGER]: "triggerHintChat",
  [WEBHOOK_TRIGGER]: "triggerHintWebhook",
};

/** `agent.run`'s answer-shape override, edited as the Builder edits an agent's own. */
const AGENT_RUN = "agent.run";
const STRUCTURED_OUTPUT = "structured_output_schema";

/** Everything a recursive field needs beyond its own schema, value and path. */
interface FieldCtx {
  node: NodeInstance;
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  bindings: readonly Binding[];
  /** Field-scoped validation messages, keyed by `target_field` path. */
  errors: ReadonlyMap<string, string>;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  upsertBinding: (binding: Binding) => void;
  removeBinding: (targetNodeId: Uuid, targetField: string) => void;
}

/** A value as an object, or an empty object when it is not one. */
function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

/** A value as an array, or an empty array when it is not one. */
function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** A string value, or null. */
function strOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Set one key of an object immutably, dropping it when the value is `undefined`. */
function setKey(
  base: Record<string, unknown>,
  key: string,
  value: unknown,
): Record<string, unknown> {
  const next = { ...base };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

/** Replace one element of an array immutably. */
function replaceAt<T>(items: readonly T[], index: number, value: T): T[] {
  return items.map((item, i) => (i === index ? value : item));
}

interface FieldProps {
  schema: Schema;
  name: string;
  required: boolean;
  path: (string | number)[];
  defs: Defs;
  ctx: FieldCtx;
}

/** A labelled group wrapping a nested object's or a union's fields. */
function Fieldset({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <fieldset className="border-border/60 space-y-3 rounded-lg border p-3">
      <legend className="text-muted-foreground px-1 text-xs font-medium">{label}</legend>
      {children}
    </fieldset>
  );
}

/** The ids a multi-select leaf holds, in order, ignoring anything that is not one. */
function idList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
}

/** `ids` with `id` added at the end, or removed if it was there. */
function toggled(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((one) => one !== id) : [...ids, id];
}

/** Knowledge collections a step searches, chosen on what is in them. */
function CollectionPin({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  const { kbs } = useKnowledgeBases();
  const selected = idList(value);
  return (
    <CollectionPicker
      collections={kbs}
      selectedIds={selected}
      onToggle={(id) => onChange(toggled(selected, id))}
      disabled={disabled}
    />
  );
}

/** Members of the organization a step addresses, chosen by name, stored by id. */
function MemberPin({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const selected = idList(value);
  return (
    <MemberPicker
      members={members}
      selected={selected}
      onToggle={(id) => onChange(toggled(selected, id))}
      label={(count) => t("pickerMembersChosen", { count })}
      scope={t("pickerMembersScope")}
      disabled={disabled}
    />
  );
}

/** A static config leaf whose value is a pinned resource, edited through a picker. */
function ResourcePin({
  kind,
  schema,
  label,
  value,
  error,
  disabled,
  onChange,
}: {
  kind: ResourceKind;
  schema: Schema;
  /** The field's own title, for a picker that labels its control; its own label when none. */
  label: string | undefined;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  if (kind === "agent") {
    const ref = record(value);
    const current: AgentVersionRef = {
      agent_id: strOrNull(ref["agent_id"]),
      version_id: strOrNull(ref["version_id"]),
    };
    return (
      <AgentVersionPicker value={current} onChange={onChange} disabled={disabled} error={error} />
    );
  }
  if (kind === "table") {
    // `kind` and `column_ids` have server defaults ("table", and null for every
    // column), so a ref authored through the API may leave both out; the table id
    // is what names one.
    const current =
      isRecord(value) && typeof value["table_id"] === "string"
        ? ({
            ...value,
            kind: "table",
            column_ids: value["column_ids"] ?? null,
          } as unknown as TableIORef)
        : null;
    return (
      <TableColumnPicker
        value={current}
        onChange={(next) => onChange(next ?? undefined)}
        disabled={disabled}
        error={error}
      />
    );
  }
  if (kind === "channel_bot") {
    return (
      <ChannelBotPicker
        label={label}
        platform={typeof schema["x-platform"] === "string" ? schema["x-platform"] : undefined}
        value={strOrNull(value)}
        onChange={(next) => onChange(next ?? undefined)}
        disabled={disabled}
        error={error}
      />
    );
  }
  if (kind === "sandbox_connection") {
    return (
      <SandboxConnectionPicker
        label={label}
        value={strOrNull(value)}
        onChange={(next) => onChange(next ?? undefined)}
        disabled={disabled}
        error={error}
      />
    );
  }
  if (kind === "collection" || kind === "member") {
    const Pin = kind === "collection" ? CollectionPin : MemberPin;
    return (
      <div className="space-y-1.5">
        <Pin value={value} disabled={disabled} onChange={onChange} />
        {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
      </div>
    );
  }
  return (
    <SecretPicker
      label={label}
      value={strOrNull(value)}
      onChange={(next) => onChange(next ?? undefined)}
      kind={secretKind(schema)}
      disabled={disabled}
      error={error}
    />
  );
}

/** A config leaf: a resource pin, an `x-bindable` binding, or a plain literal control. */
function ConfigLeaf({
  schema,
  name,
  required,
  path,
  ctx,
  value,
  onChange,
}: FieldProps & { value: unknown; onChange: (value: unknown) => void }) {
  const field = bindingFieldPath(path);
  const error = ctx.errors.get(field);
  const label = labelOf(schema, name);
  const resource = resourceKind(schema);

  if (resource !== null) {
    // Only the collection and member pins leave their label to the form: the
    // other pickers label their own controls, the secret, bot and host ones
    // with the field's name.
    const labelled = resource !== "collection" && resource !== "member";
    return (
      <div className="space-y-1.5">
        {!labelled && <Label>{label}</Label>}
        <ResourcePin
          kind={resource}
          schema={schema}
          label={ownTitle(schema, name)}
          value={value}
          error={error}
          disabled={ctx.disabled}
          onChange={onChange}
        />
      </div>
    );
  }

  if (isBindable(schema)) {
    return (
      <BindingField
        targetNodeId={ctx.node.id}
        targetField={field}
        name={name}
        schema={schema}
        required={required}
        bindings={ctx.bindings}
        graph={ctx.graph}
        catalog={ctx.catalog}
        error={error}
        disabled={ctx.disabled}
        onUpsert={ctx.upsertBinding}
        onRemove={ctx.removeBinding}
      />
    );
  }

  return (
    <SchemaForm
      schema={singleFieldSchema(name, schema, required)}
      value={value === undefined ? {} : { [name]: value }}
      idPrefix={`cfg-${field.replace(/[^a-zA-Z0-9]+/g, "-")}`}
      disabled={ctx.disabled}
      errors={error === undefined ? undefined : { [name]: error }}
      onChange={(next) => onChange(next[name])}
    />
  );
}

/** A discriminated union: a discriminator `Select`, then the chosen branch's fields. */
function ConfigUnion({
  shape,
  label,
  path,
  defs,
  ctx,
  value,
  onChange,
}: {
  shape: UnionShape;
  label: string;
  path: (string | number)[];
  defs: Defs;
  ctx: FieldCtx;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const rec = record(value);
  const current =
    typeof rec[shape.discriminator] === "string" ? (rec[shape.discriminator] as string) : "";
  const branch = shape.branches.find((candidate) => candidate.value === current);

  const select = (next: string) => {
    // Switching branch discards the old branch's fields *and* any bindings nested
    // under this path — a stale shape is discarded wholesale, never merged.
    applyRebase(
      rebaseClear(ctx.bindings, ctx.node.id, path.map(String)),
      ctx.node.id,
      ctx.upsertBinding,
      ctx.removeBinding,
    );
    onChange({ [shape.discriminator]: next });
  };

  return (
    <Fieldset label={label}>
      <Select value={current} onValueChange={select} disabled={ctx.disabled}>
        <SelectTrigger aria-label={t("nodeFormUnionLabel", { field: label })}>
          <SelectValue placeholder={t("nodeFormUnionPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {shape.branches.map((candidate) => (
            <SelectItem key={candidate.value} value={candidate.value}>
              {candidate.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {branch !== undefined &&
        objectFields(branch.schema, defs).map((child) => (
          <ConfigNode
            key={child.name}
            schema={child.schema}
            name={child.name}
            required={child.required}
            path={[...path, child.name]}
            defs={defs}
            ctx={ctx}
            value={rec[child.name]}
            onChange={(next) => onChange(setKey(record(value), child.name, next))}
          />
        ))}
    </Fieldset>
  );
}

/** An array of objects: add / remove / reorder repeatable rows over the recursive renderer. */
function ConfigArray({
  shape,
  label,
  path,
  defs,
  ctx,
  value,
  onChange,
}: {
  shape: { items: Schema };
  label: string;
  path: (string | number)[];
  defs: Defs;
  ctx: FieldCtx;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const rows = asArray(value);
  const prefix = path.map(String);
  const fields = objectFields(shape.items, defs);

  const add = () => onChange([...rows, {}]);

  const remove = (index: number) => {
    applyRebase(
      rebaseRemove(ctx.bindings, ctx.node.id, prefix, index),
      ctx.node.id,
      ctx.upsertBinding,
      ctx.removeBinding,
    );
    const next = rows.filter((_, i) => i !== index);
    onChange(next.length === 0 ? undefined : next);
  };

  const move = (index: number, target: number) => {
    applyRebase(
      rebaseSwap(ctx.bindings, ctx.node.id, prefix, index, target),
      ctx.node.id,
      ctx.upsertBinding,
      ctx.removeBinding,
    );
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <Fieldset label={label}>
      {rows.map((row, index) => (
        <div key={index} className="border-border/60 space-y-3 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground text-xs">
              {t("nodeFormRow", { index: index + 1 })}
            </span>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("nodeFormMoveUp", { index: index + 1 })}
                disabled={ctx.disabled || index === 0}
                onClick={() => move(index, index - 1)}
              >
                <ArrowUp />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("nodeFormMoveDown", { index: index + 1 })}
                disabled={ctx.disabled || index === rows.length - 1}
                onClick={() => move(index, index + 1)}
              >
                <ArrowDown />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("nodeFormRemoveRow", { index: index + 1 })}
                disabled={ctx.disabled}
                onClick={() => remove(index)}
              >
                <Trash2 />
              </Button>
            </div>
          </div>
          {fields.map((child) => (
            <ConfigNode
              key={child.name}
              schema={child.schema}
              name={child.name}
              required={child.required}
              path={[...path, index, child.name]}
              defs={defs}
              ctx={ctx}
              value={record(row)[child.name]}
              onChange={(next) =>
                onChange(replaceAt(rows, index, setKey(record(row), child.name, next)))
              }
            />
          ))}
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" disabled={ctx.disabled} onClick={add}>
        <Plus />
        {t("nodeFormAddRow")}
      </Button>
    </Fieldset>
  );
}

/** One config field, dispatched by its resolved shape. Recurses for objects, arrays and unions. */
function ConfigNode({
  schema,
  name,
  required,
  path,
  defs,
  ctx,
  value,
  onChange,
}: FieldProps & { value: unknown; onChange: (value: unknown) => void }) {
  const shape = classify(schema, defs);
  const label = labelOf(schema, name);

  if (shape.kind === "object") {
    return (
      <Fieldset label={label}>
        {shape.entries.map((child) => (
          <ConfigNode
            key={child.name}
            schema={child.schema}
            name={child.name}
            required={child.required}
            path={[...path, child.name]}
            defs={defs}
            ctx={ctx}
            value={record(value)[child.name]}
            onChange={(next) => onChange(setKey(record(value), child.name, next))}
          />
        ))}
      </Fieldset>
    );
  }

  if (shape.kind === "union") {
    return (
      <ConfigUnion
        shape={shape}
        label={label}
        path={path}
        defs={defs}
        ctx={ctx}
        value={value}
        onChange={onChange}
      />
    );
  }

  if (shape.kind === "array") {
    return (
      <ConfigArray
        shape={shape}
        label={label}
        path={path}
        defs={defs}
        ctx={ctx}
        value={value}
        onChange={onChange}
      />
    );
  }

  return (
    <ConfigLeaf
      schema={schema}
      name={name}
      required={required}
      path={path}
      defs={defs}
      ctx={ctx}
      value={value}
      onChange={onChange}
    />
  );
}

/** One input field: a nested object recurses; anything else is bound wholesale. */
function InputNode({ schema, name, required, path, defs, ctx }: FieldProps) {
  const shape = classify(schema, defs);
  const label = labelOf(schema, name);

  if (shape.kind === "object") {
    return (
      <Fieldset label={label}>
        {shape.entries.map((child) => (
          <InputNode
            key={child.name}
            schema={child.schema}
            name={child.name}
            required={child.required}
            path={[...path, child.name]}
            defs={defs}
            ctx={ctx}
          />
        ))}
      </Fieldset>
    );
  }

  const field = bindingFieldPath(path);
  return (
    <BindingField
      targetNodeId={ctx.node.id}
      targetField={field}
      name={name}
      schema={schema}
      required={required}
      bindings={ctx.bindings}
      graph={ctx.graph}
      catalog={ctx.catalog}
      error={ctx.errors.get(field)}
      disabled={ctx.disabled}
      onUpsert={ctx.upsertBinding}
      onRemove={ctx.removeBinding}
    />
  );
}

export interface NodeFormProps {
  definition: NodeDefinition;
  node: NodeInstance;
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  bindings: readonly Binding[];
  /** Field-scoped validation messages for this node, keyed by `target_field` path. */
  errors: ReadonlyMap<string, string>;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  upsertBinding: (binding: Binding) => void;
  removeBinding: (targetNodeId: Uuid, targetField: string) => void;
}

/**
 * The form for one node — its static `config_schema` settings, then its
 * `input_schema` bindings — extending `schema-form.tsx` with `$ref`, nested
 * objects, repeatable arrays, discriminated unions and binding-aware leaves.
 */
export function NodeForm({
  definition,
  node,
  graph,
  catalog,
  bindings,
  errors,
  disabled,
  updateNodeConfig,
  upsertBinding,
  removeBinding,
}: NodeFormProps) {
  const t = useTranslations("workflows");
  const ctx: FieldCtx = {
    node,
    graph,
    catalog,
    bindings,
    errors,
    disabled,
    updateNodeConfig,
    upsertBinding,
    removeBinding,
  };

  if (definition.id === SCHEDULE_TRIGGER) {
    return (
      <ScheduleTriggerForm node={node} disabled={disabled} updateNodeConfig={updateNodeConfig} />
    );
  }
  if (definition.id === MANUAL_TRIGGER) {
    return (
      <div className="space-y-4">
        <p className="text-muted-foreground text-xs">{t("triggerHintManual")}</p>
        <InputFieldsForm node={node} disabled={disabled} updateNodeConfig={updateNodeConfig} />
      </div>
    );
  }

  const configSchema = definition.config_schema;
  const inputSchema = definition.input_schema;
  const configFields =
    configSchema === null ? [] : objectFields(configSchema, defsOf(configSchema));
  const inputFields = inputSchema === null ? [] : objectFields(inputSchema, defsOf(inputSchema));
  const configDefs = configSchema === null ? {} : defsOf(configSchema);
  const inputDefs = inputSchema === null ? {} : defsOf(inputSchema);

  if (configFields.length === 0 && inputFields.length === 0) {
    const hint = TRIGGER_HINTS[definition.id];
    return (
      <p className="text-muted-foreground text-xs">
        {hint === undefined ? t("nodeFormNoFields") : t(hint)}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {configFields.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide uppercase">
            {t("nodeFormConfigSection")}
          </h3>
          {configFields.map((entry) =>
            definition.id === AGENT_RUN && entry.name === STRUCTURED_OUTPUT ? (
              <AnswerFormatForm
                key={entry.name}
                value={isRecord(node.config[entry.name]) ? record(node.config[entry.name]) : null}
                onChange={(next) =>
                  updateNodeConfig(node.id, setKey(node.config, entry.name, next ?? undefined))
                }
                disabled={disabled}
                keepsOwn
              />
            ) : (
              <ConfigNode
                key={entry.name}
                schema={entry.schema}
                name={entry.name}
                required={entry.required}
                path={[entry.name]}
                defs={configDefs}
                ctx={ctx}
                value={node.config[entry.name]}
                onChange={(next) =>
                  updateNodeConfig(node.id, setKey(node.config, entry.name, next))
                }
              />
            ),
          )}
        </section>
      )}
      {inputFields.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide uppercase">
            {t("nodeFormInputSection")}
          </h3>
          {inputFields.map((entry) => (
            <InputNode
              key={entry.name}
              schema={entry.schema}
              name={entry.name}
              required={entry.required}
              path={[entry.name]}
              defs={inputDefs}
              ctx={ctx}
            />
          ))}
        </section>
      )}
    </div>
  );
}
