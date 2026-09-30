"use client";

import { type DragEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import {
  Input,
  Label,
  Textarea,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SchemaForm } from "@/components/agents/schema-form";
import { availableSourceNodes, isDynamic } from "@/components/workflows/validation";
import { carriesField, droppedField, observedFits } from "@/lib/workflows/field-drag";
import type { Binding, NodeCatalog, Uuid, WorkflowGraph } from "@/lib/workflows/types";

import {
  bindingFor,
  candidateByKey,
  candidateForField,
  candidateForBinding,
  isNodeOutput,
  literalBinding,
  literalValueOf,
  nodeOutputBinding,
  sourceCandidates,
} from "./bindings";
import type { SourceCandidate } from "./bindings";
import { labelOf, singleFieldSchema, unwrapOptional, type Schema } from "./schema-model";

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
 * One binding-aware leaf: a value typed in place (a `LiteralValue`), or read from
 * an upstream node's output (a `NodeOutputRef`), chosen by a toggle.
 *
 * It reads and writes only the flat `bindings` list, never `config`. Literal mode
 * wraps `schema-form.tsx`'s existing scalar control — so masking, `x-multiline`,
 * enums and suggestions all come for free — and stores what it produces as a
 * literal binding. Binding mode offers a `Select` of every reachable,
 * type-compatible upstream output (rule 4 ∩ rule 3) and stores the chosen one as a
 * node-output binding. Toggling replaces the source wholesale rather than merging a
 * stale shape.
 *
 * A field dragged from the step dialog's Input pane binds it the same way, and is
 * refused with the reason when it is none of the sources the picker would offer.
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
  const boundToNode = isNodeOutput(binding);
  // Binding mode with no source chosen yet has no binding to derive from, so it is
  // held locally until a source is picked (or the toggle is turned back off).
  const [pendingBind, setPendingBind] = useState(false);
  const bindingMode = boundToNode || pendingBind;
  const label = labelOf(schema, name);

  const candidates = useMemo(
    () => sourceCandidates(graph, catalog, targetNodeId, schema),
    [graph, catalog, targetNodeId, schema],
  );

  const idPrefix = `bind-${targetField.replace(/[^a-zA-Z0-9]+/g, "-")}`;

  const toggle = (next: boolean) => {
    if (next) {
      setPendingBind(true);
      if (binding !== undefined && binding.source.kind === "literal") {
        onRemove(targetNodeId, targetField);
      }
    } else {
      setPendingBind(false);
      if (boundToNode) onRemove(targetNodeId, targetField);
    }
  };

  const current = candidateForBinding(candidates, binding);
  const bindTo = (candidate: SourceCandidate, extraPath: readonly string[]) =>
    onUpsert(
      nodeOutputBinding(targetNodeId, targetField, candidate.nodeId, candidate.port, [
        ...candidate.fieldPath,
        ...extraPath,
      ]),
    );

  const chooseSource = (key: string) => {
    const candidate = candidateByKey(candidates, key);
    // The `Select` only emits a candidate's own key, so a lookup always resolves.
    if (candidate !== undefined) bindTo(candidate, []);
  };

  const currentKey = current?.candidate.key ?? "";

  const changeLiteral = (next: Record<string, unknown>) => {
    const value = next[name];
    if (value === undefined) onRemove(targetNodeId, targetField);
    else onUpsert(literalBinding(targetNodeId, targetField, value));
  };

  const literalValue = literalValueOf(binding);

  const [dropping, setDropping] = useState(false);
  const [dropProblem, setDropProblem] = useState<string | null>(null);
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDropping(false);
    const field = droppedField(event);
    if (field === null) return;
    const found = candidateForField(candidates, field.nodeId, field.path);
    // A field inside a free-form value has no declared type: the run it came from
    // says what it holds.
    const fits =
      found !== undefined &&
      (found.extraPath.length === 0 || observedFits(unwrapOptional(schema)["type"], field.type));
    if (found !== undefined && fits) {
      setDropProblem(null);
      setPendingBind(false);
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

  return (
    // The mode sits in the label's row, at its right: whether the field holds a
    // value typed here or one an earlier step hands on. Dropping a dragged field
    // is the pointer's shortcut; the source picker is the way a keyboard gets there.
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
      <div
        role="radiogroup"
        aria-label={t("bindingToggleLabel", { field: label })}
        className="bg-muted absolute top-0 right-0 z-10 flex rounded-md p-0.5 text-[11px]"
      >
        {[false, true].map((fromStep) => (
          <button
            key={String(fromStep)}
            type="button"
            role="radio"
            aria-checked={bindingMode === fromStep}
            disabled={disabled}
            onClick={() => bindingMode !== fromStep && toggle(fromStep)}
            className={cn(
              "rounded px-2 py-0.5 font-medium transition-colors disabled:opacity-50",
              bindingMode === fromStep
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {fromStep ? t("bindingModeStep") : t("bindingModeValue")}
          </button>
        ))}
      </div>

      {bindingMode ? (
        <div className="space-y-1.5">
          <Label>
            {label}
            {required && <span className="text-muted-foreground"> *</span>}
          </Label>
          {candidates.length === 0 ? (
            <p className="text-muted-foreground text-xs">{t("bindingNoSources")}</p>
          ) : (
            <Select value={currentKey} onValueChange={chooseSource} disabled={disabled}>
              <SelectTrigger aria-label={t("bindingSourceLabel", { field: label })}>
                <SelectValue placeholder={t("bindingSourcePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((candidate) => (
                  <SelectItem key={candidate.key} value={candidate.key}>
                    {candidate.fieldPath.length === 0
                      ? t("bindingSourceOption", {
                          node: candidate.nodeLabel,
                          port: candidate.portLabel,
                          type: candidate.typeToken,
                        })
                      : t("bindingSourceFieldOption", {
                          node: candidate.nodeLabel,
                          port: candidate.portLabel,
                          field: candidate.fieldPath.join("."),
                          type: candidate.typeToken,
                        })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
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
      ) : isDynamic(unwrapOptional(schema)) ? (
        <JsonLiteral
          key={`${targetNodeId}:${targetField}`}
          id={`${idPrefix}-json`}
          label={label}
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
          onChange={changeLiteral}
        />
      )}
      {dropProblem !== null && <p className="text-destructive text-xs">{dropProblem}</p>}
    </div>
  );
}

/**
 * A free-form value typed as JSON - a record's `values`, an error's `details` -
 * which no generated control can edit. Parsed when the box loses focus; a value
 * that does not parse is reported and not written.
 */
function JsonLiteral({
  id,
  label,
  value,
  error,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslations("workflows");
  const [invalid, setInvalid] = useState(false);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        className="font-mono text-xs"
        rows={4}
        disabled={disabled}
        // i18n-exempt: JSON syntax shown as an example, and braces are ICU syntax in the catalog.
        placeholder='{"Score": 100}'
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
