"use client";

import { type DragEvent, useMemo, useState } from "react";
import { Braces, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { Input, Label, Textarea } from "@/components/ui";
import { SchemaForm } from "@/components/agents/schema-form";
import { availableSourceNodes, isDynamic } from "@/components/workflows/validation";
import { carriesField, droppedField, observedFits } from "@/lib/workflows/field-drag";
import { plainType } from "@/lib/workflows/plain-types";
import type { Binding, NodeCatalog, Uuid, WorkflowGraph } from "@/lib/workflows/types";

import {
  bindingFor,
  candidateForBinding,
  candidateForField,
  isNodeOutput,
  literalBinding,
  literalValueOf,
  nodeOutputBinding,
  sourceCandidates,
} from "./bindings";
import type { SourceCandidate } from "./bindings";
import { DataSourceMenu, sourceText } from "./data-source";
import { nodeNames } from "./problems";
import {
  labelOf,
  singleFieldSchema,
  takesJson,
  takesText,
  unwrapOptional,
  type Schema,
} from "./schema-model";
import { TextValueField } from "./text-value-field";

export interface BindingFieldProps {
  /** The node this field belongs to. */
  targetNodeId: Uuid;
  /** The field's `Binding.target_field` — a name, or a JSON-Pointer path for a nested leaf. */
  targetField: string;
  /** The field's name, for its label and its wrapped scalar control. */
  name: string;
  /** The field's leaf schema — its literal control, and the type its sources must match. */
  schema: Schema;
  required: boolean;
  /** The graph's flat binding list. */
  bindings: readonly Binding[];
  /** The whole graph and catalog, for computing reachable, type-compatible sources. */
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  /** A field-scoped validation message, shown in the wrapped control's error slot. */
  error?: string;
  disabled?: boolean;
  onUpsert: (binding: Binding) => void;
  onRemove: (targetNodeId: Uuid, targetField: string) => void;
}

/**
 * One binding-aware parameter: a value typed in place, or one an earlier step
 * hands on - with no mode to choose between them, the way n8n's parameters work.
 *
 * Free text (`takesText`) is one box that takes typed text and values from
 * earlier steps together (`TextValueField`). Any other field is its own control
 * - a number, a choice, a switch, JSON - with **Data** beside it, which reads the
 * value from an earlier step instead; the field then shows which step and field
 * it reads, with an x to type a value again. A field dragged from the step
 * dialog's Input pane does the same, and is refused with the reason when it is
 * none of the values the menu would offer.
 *
 * It reads and writes only the flat `bindings` list, never `config`. The values
 * offered are every reachable, type-compatible upstream output (rule 4 ∩ rule 3).
 */
export function BindingField({
  targetNodeId,
  targetField,
  name,
  schema,
  required,
  bindings,
  graph,
  catalog,
  error,
  disabled,
  onUpsert,
  onRemove,
}: BindingFieldProps) {
  const t = useTranslations("workflows");
  const binding = bindingFor(bindings, targetNodeId, targetField);
  const label = labelOf(schema, name);
  const own = unwrapOptional(schema);
  const names = useMemo(() => nodeNames(graph, catalog), [graph, catalog]);
  const candidates = useMemo(
    () => sourceCandidates(graph, catalog, targetNodeId, schema),
    [graph, catalog, targetNodeId, schema],
  );
  const idPrefix = `bind-${targetField.replace(/[^a-zA-Z0-9]+/g, "-")}`;

  const current = candidateForBinding(candidates, binding);
  const bindTo = (candidate: SourceCandidate, extraPath: readonly string[]) =>
    onUpsert(
      nodeOutputBinding(targetNodeId, targetField, candidate.nodeId, candidate.port, [
        ...candidate.fieldPath,
        ...extraPath,
      ]),
    );

  const [dropping, setDropping] = useState(false);
  const [dropProblem, setDropProblem] = useState<string | null>(null);
  const reads = isNodeOutput(binding);
  const textual = !reads && (takesText(schema) || binding?.source.kind === "template");
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDropping(false);
    // Text takes a dropped field as a placeholder instead (`TextValueField`).
    if (textual) return;
    const field = droppedField(event);
    if (field === null) return;
    const found = candidateForField(candidates, field.nodeId, field.path);
    // A field inside a free-form value has no declared type: the run it came from
    // says what it holds.
    const fits =
      found !== undefined &&
      (found.extraPath.length === 0 || observedFits(own["type"], field.type));
    if (found !== undefined && fits) {
      setDropProblem(null);
      bindTo(found.candidate, found.extraPath);
      return;
    }
    const reachable =
      found !== undefined || availableSourceNodes(graph, catalog, targetNodeId).has(field.nodeId);
    setDropProblem(
      reachable
        ? t("bindingDropIncompatible", { field: field.path.join("."), target: label })
        : t("bindingDropUnreachable"),
    );
  };
  const over = (event: DragEvent) => {
    if (disabled || !carriesField(event)) return;
    event.preventDefault();
    setDropping(true);
  };

  const menu = (
    <DataSourceMenu
      candidates={candidates}
      names={names}
      label={t("dataSourceRead", { field: label })}
      pressed={reads}
      onPick={(candidate) => bindTo(candidate, [])}
    />
  );
  const description = typeof own["description"] === "string" ? own["description"] : undefined;

  let control: React.ReactNode;
  if (reads) {
    control = (
      <div className="space-y-1.5">
        <div className="flex min-h-6 items-center justify-between gap-2">
          <Label>
            {label}
            {required && <span className="text-muted-foreground"> *</span>}
          </Label>
          {!disabled && (
            <div className="flex items-center gap-0.5">
              {menu}
              <button
                type="button"
                aria-label={t("dataSourceClear", { field: label })}
                title={t("dataSourceClear", { field: label })}
                onClick={() => onRemove(targetNodeId, targetField)}
                className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex size-6 items-center justify-center rounded-md outline-none focus-visible:ring-2"
              >
                <X aria-hidden="true" className="size-3.5" />
              </button>
            </div>
          )}
        </div>
        <div className="border-border bg-muted/40 flex min-h-9 items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
          <Braces aria-hidden="true" className="text-muted-foreground size-3.5 shrink-0" />
          <span className="truncate">
            {current === undefined
              ? t("dataSourceGone")
              : sourceText(current.candidate, names, candidates)}
            {current !== undefined && current.extraPath.length > 0 && (
              <span className="text-muted-foreground"> › {current.extraPath.join(".")}</span>
            )}
          </span>
          {current !== undefined && (
            <span className="text-muted-foreground ml-auto shrink-0 text-xs">
              {t(`dataType.${plainType(current.candidate.typeToken)}`)}
            </span>
          )}
        </div>
        {current?.candidate.dynamic && (
          <div className="space-y-1">
            <Label htmlFor={`${idPrefix}-path`} className="text-muted-foreground text-xs">
              {t("bindingPathLabel")}
            </Label>
            <Input
              // Uncontrolled, so a half-typed path is not written on every key;
              // keyed so another node's or another source's path starts fresh.
              key={`${targetNodeId}:${current.candidate.key}`}
              id={`${idPrefix}-path`}
              className="font-mono text-xs"
              placeholder={t("bindingPathPlaceholder")}
              disabled={disabled}
              defaultValue={current.extraPath.join(".")}
              onBlur={(event) =>
                bindTo(
                  current.candidate,
                  event.target.value
                    .split(".")
                    .map((part) => part.trim())
                    .filter((part) => part.length > 0),
                )
              }
            />
          </div>
        )}
        {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
      </div>
    );
  } else if (textual) {
    control = (
      <TextValueField
        targetNodeId={targetNodeId}
        targetField={targetField}
        label={label}
        required={required}
        hint={description}
        placeholder={typeof own["x-placeholder"] === "string" ? own["x-placeholder"] : undefined}
        multiline={own["x-multiline"] === true || own["x-textarea"] === true}
        binding={binding}
        graph={graph}
        catalog={catalog}
        idPrefix={idPrefix}
        error={error}
        disabled={disabled}
        onUpsert={onUpsert}
        onRemove={onRemove}
      />
    );
  } else {
    const literalValue = literalValueOf(binding);
    control = (
      <>
        {!disabled && <div className="absolute top-0 right-0 z-10">{menu}</div>}
        {isDynamic(own) || takesJson(schema) ? (
          <JsonLiteral
            key={`${targetNodeId}:${targetField}`}
            id={`${idPrefix}-json`}
            label={label}
            required={required}
            list={own["type"] === "array"}
            value={literalValue}
            error={error}
            disabled={disabled}
            onChange={(value) =>
              value === undefined
                ? onRemove(targetNodeId, targetField)
                : onUpsert(literalBinding(targetNodeId, targetField, value))
            }
          />
        ) : (
          <SchemaForm
            schema={singleFieldSchema(name, schema, required)}
            value={literalValue === undefined ? {} : { [name]: literalValue }}
            idPrefix={idPrefix}
            disabled={disabled}
            errors={error === undefined ? undefined : { [name]: error }}
            onChange={(next) => {
              const value = next[name];
              if (value === undefined) onRemove(targetNodeId, targetField);
              else onUpsert(literalBinding(targetNodeId, targetField, value));
            }}
          />
        )}
      </>
    );
  }

  return (
    // Dropping a dragged field is the pointer's shortcut; **Data** is the way a
    // keyboard gets there.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      className={cn(
        "relative space-y-2 rounded-md",
        dropping && "ring-ring ring-offset-background ring-2 ring-offset-4",
      )}
      onDragOver={over}
      onDragLeave={() => setDropping(false)}
      onDrop={drop}
    >
      {control}
      {dropProblem !== null && <p className="text-destructive text-xs">{dropProblem}</p>}
    </div>
  );
}

/**
 * A value typed as JSON - a free-form one, a record's `values` or an error's
 * `details`, or a list of records - which no generated control can edit. Parsed
 * when the box loses focus; a value that does not parse is reported and not
 * written.
 */
function JsonLiteral({
  id,
  label,
  required,
  list,
  value,
  error,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  required: boolean;
  /** A list is asked for, so the example is one. */
  list: boolean;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const [invalid, setInvalid] = useState(false);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-muted-foreground"> *</span>}
      </Label>
      <Textarea
        id={id}
        className="font-mono text-xs"
        rows={4}
        disabled={disabled}
        // i18n-exempt: JSON syntax shown as an example, and braces are ICU syntax in the catalog.
        placeholder={list ? '[{"name": "Ada", "score": 90}]' : '{"Score": 100}'}
        defaultValue={value === undefined ? "" : JSON.stringify(value, null, 2)}
        onBlur={(event) => {
          const text = event.target.value.trim();
          if (text === "") {
            setInvalid(false);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(text));
            setInvalid(false);
          } catch {
            setInvalid(true);
          }
        }}
      />
      {invalid && <p className="text-destructive text-xs">{t("bindingJsonInvalid")}</p>}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
