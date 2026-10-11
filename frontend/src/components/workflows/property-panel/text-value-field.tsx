"use client";

import { type DragEvent, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Input, Label, Textarea } from "@/components/ui";
import { droppedField } from "@/lib/workflows/field-drag";
import {
  parseTemplate,
  placeholderText,
  previewTemplate,
  templateText,
} from "@/lib/workflows/template-text";
import {
  outputRefs,
  type Binding,
  type NodeCatalog,
  type NodeOutputRef,
  type Uuid,
  type WorkflowGraph,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { candidateForField, sourceCandidates, type SourceCandidate } from "./bindings";
import { DataSourceMenu } from "./data-source";
import { nodeNames } from "./problems";

/** A placeholder may name any value in reach: whatever it holds becomes text. */
const ANY_VALUE = {};

/** The reference a picked source is, with any path typed past a free-form value. */
function refOf(candidate: SourceCandidate, extraPath: readonly string[] = []): NodeOutputRef {
  return {
    kind: "node_output",
    node_id: candidate.nodeId,
    port: candidate.port,
    field_path: [...candidate.fieldPath, ...extraPath],
  };
}

/** What the field holds as text: a literal string, or a template written out. */
function textOf(binding: Binding | undefined, names: ReadonlyMap<Uuid, string>): string {
  if (binding?.source.kind === "template") return templateText(binding.source, names);
  if (binding?.source.kind === "literal" && typeof binding.source.value === "string") {
    return binding.source.value;
  }
  return "";
}

export interface TextValueFieldProps {
  targetNodeId: Uuid;
  targetField: string;
  label: string;
  required: boolean;
  /** The field's description, under it. */
  hint?: string;
  placeholder?: string;
  /** A box several lines tall, for a message or a prompt. */
  multiline: boolean;
  /** The field's binding now: a literal string, a template, or none. */
  binding: Binding | undefined;
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  idPrefix: string;
  error?: string;
  disabled?: boolean;
  onUpsert: (binding: Binding) => void;
  onRemove: (targetNodeId: Uuid, targetField: string) => void;
}

/**
 * A text parameter that takes typed text and values from earlier steps in one
 * box, the way n8n's does: `New lead: {{Form.payload.name}}`. There is no mode
 * to choose - **Data** inserts a value at the cursor, and so does a field dragged
 * from the Input pane.
 *
 * Text with no placeholder is stored as it is; with one, as a template the run
 * renders. It is written as it is typed, so nothing is lost when the dialog
 * closes; a placeholder naming nothing in reach is not written, and is said once
 * the box is left. A placeholder names a step by its id underneath, so renaming
 * the step renames it here. With a test run's data, the result is previewed.
 */
export function TextValueField({
  targetNodeId,
  targetField,
  label,
  required,
  hint,
  placeholder,
  multiline,
  binding,
  graph,
  catalog,
  idPrefix,
  error,
  disabled,
  onUpsert,
  onRemove,
}: TextValueFieldProps) {
  const t = useTranslations("workflows");
  const stepData = useWorkflowEditorStore((state) => state.stepData);
  const box = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const names = useMemo(() => nodeNames(graph, catalog), [graph, catalog]);
  const candidates = useMemo(
    () => sourceCandidates(graph, catalog, targetNodeId, ANY_VALUE),
    [graph, catalog, targetNodeId],
  );
  const saved = textOf(binding, names);
  const [text, setText] = useState(saved);
  const [seen, setSeen] = useState(saved);
  const [unknown, setUnknown] = useState<string | null>(null);
  // Written elsewhere - a drop, a rename, an undo - the box shows what was saved.
  if (saved !== seen) {
    setSeen(saved);
    if (saved !== text) setText(saved);
  }

  const resolve = (nodeId: Uuid, path: string[]): NodeOutputRef | null => {
    const found = candidateForField(candidates, nodeId, path);
    return found === undefined ? null : refOf(found.candidate, found.extraPath);
  };

  /** Write `next`; `left`, the box was left, so a placeholder naming nothing is said. */
  const write = (next: string, left: boolean) => {
    if (next === "") {
      setUnknown(null);
      if (binding !== undefined) onRemove(targetNodeId, targetField);
      return;
    }
    const parsed = parseTemplate(next, names, resolve);
    if ("unknown" in parsed) {
      if (left) setUnknown(parsed.unknown);
      return;
    }
    setUnknown(null);
    const placeholders = parsed.parts.some((part) => typeof part !== "string");
    onUpsert({
      target_node_id: targetNodeId,
      target_field: targetField,
      source: placeholders
        ? { kind: "template", parts: parsed.parts }
        : { kind: "literal", value: next },
    });
  };

  const change = (next: string) => {
    setText(next);
    write(next, false);
  };

  /** Put `ref`'s placeholder at the cursor, or at the end, and write the result. */
  const insert = (ref: NodeOutputRef) => {
    const element = box.current;
    const focused = element !== null && document.activeElement === element;
    const at = focused ? (element.selectionStart ?? text.length) : text.length;
    change(
      `${text.slice(0, at)}${placeholderText(ref.node_id, ref.field_path, names)}${text.slice(at)}`,
    );
  };

  const drop = (event: DragEvent) => {
    const field = droppedField(event);
    if (field === null) return;
    event.preventDefault();
    const ref = resolve(field.nodeId, field.path);
    if (ref === null) setUnknown(placeholderText(field.nodeId, field.path, names));
    else insert(ref);
  };

  const template = binding?.source.kind === "template" ? binding.source : undefined;
  const preview = template === undefined ? null : previewTemplate(template, stepData, names);
  // Shown once a run has something for at least one placeholder.
  const previewed =
    template !== undefined &&
    preview !== null &&
    preview.missing.length < outputRefs(template).length;
  const id = `${idPrefix}-text`;
  const Box = multiline ? Textarea : Input;

  return (
    // A dropped field becomes a placeholder; the Data menu is the keyboard's way.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div className="space-y-1.5" onDrop={drop}>
      <div className="flex min-h-6 items-center justify-between gap-2">
        <Label htmlFor={id}>
          {label}
          {required && <span className="text-muted-foreground"> *</span>}
        </Label>
        {!disabled && (
          <DataSourceMenu
            candidates={candidates}
            names={names}
            label={t("dataSourceInsert", { field: label })}
            onPick={(candidate) => insert(refOf(candidate))}
          />
        )}
      </div>
      <Box
        ref={box}
        id={id}
        rows={multiline ? 3 : undefined}
        value={text}
        disabled={disabled}
        placeholder={placeholder}
        aria-invalid={error !== undefined || unknown !== null}
        onChange={(event: { target: { value: string } }) => change(event.target.value)}
        onBlur={() => write(text, true)}
      />
      {hint !== undefined && <p className="text-muted-foreground text-xs">{hint}</p>}
      {unknown !== null && (
        <p className="text-destructive text-xs">{t("templateUnknown", { placeholder: unknown })}</p>
      )}
      {previewed && (
        <p className="text-muted-foreground text-xs">
          <span className="font-medium">{t("templatePreview")}</span> {preview.text}
        </p>
      )}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
