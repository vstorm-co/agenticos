"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { SchemaForm } from "@/components/agents/schema-form";
import type { Binding, NodeCatalog, Uuid, WorkflowGraph } from "@/lib/workflows/types";

import {
  bindingFor,
  candidateByKey,
  candidateKey,
  isNodeOutput,
  literalBinding,
  literalValueOf,
  nodeOutputBinding,
  sourceCandidates,
} from "./bindings";
import { labelOf, singleFieldSchema, type Schema } from "./schema-model";

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

  const chooseSource = (key: string) => {
    const candidate = candidateByKey(candidates, key);
    // The `Select` only emits a candidate's own key, so a lookup always resolves.
    if (candidate !== undefined) {
      onUpsert(nodeOutputBinding(targetNodeId, targetField, candidate.nodeId, candidate.port));
    }
  };

  const currentKey =
    binding !== undefined && binding.source.kind === "node_output"
      ? candidateKey(binding.source.node_id, binding.source.port)
      : "";

  const changeLiteral = (next: Record<string, unknown>) => {
    const value = next[name];
    if (value === undefined) onRemove(targetNodeId, targetField);
    else onUpsert(literalBinding(targetNodeId, targetField, value));
  };

  const literalValue = literalValueOf(binding);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground text-xs">{t("bindingToggleCaption")}</span>
        <Switch
          aria-label={t("bindingToggleLabel", { field: label })}
          checked={bindingMode}
          disabled={disabled}
          onCheckedChange={toggle}
        />
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
                    {t("bindingSourceOption", {
                      node: candidate.nodeLabel,
                      port: candidate.portLabel,
                      type: candidate.typeToken,
                    })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
        </div>
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
    </div>
  );
}
