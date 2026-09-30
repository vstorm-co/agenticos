"use client";

import { type DragEvent, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
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
  type TemplateValue,
  type Uuid,
  type WorkflowGraph,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import {
  candidateByKey,
  candidateForField,
  sourceCandidates,
  type SourceCandidate,
} from "./bindings";
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

export interface TemplateFieldProps {
  targetNodeId: Uuid;
  targetField: string;
  label: string;
  template: TemplateValue | undefined;
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  idPrefix: string;
  error?: string;
  disabled?: boolean;
  onUpsert: (binding: Binding) => void;
  onRemove: (targetNodeId: Uuid, targetField: string) => void;
}

/**
 * Text with values from earlier steps in it: `New lead: {{Form.payload.name}}`.
 *
 * A placeholder names a step and a path into its output, and is kept by the
 * step's id, so renaming the step renames it here. **Insert a value** adds one at
 * the cursor, and so does a field dragged from the Input pane. The text is read
 * when the box loses focus; a placeholder naming nothing in reach is reported and
 * not written. With a test run's data, the result is previewed beneath.
 */
export function TemplateField({
  targetNodeId,
  targetField,
  label,
  template,
  graph,
  catalog,
  idPrefix,
  error,
  disabled,
  onUpsert,
  onRemove,
}: TemplateFieldProps) {
  const t = useTranslations("workflows");
  const stepData = useWorkflowEditorStore((state) => state.stepData);
  const box = useRef<HTMLTextAreaElement>(null);
  const [unknown, setUnknown] = useState<string | null>(null);
  const names = useMemo(() => nodeNames(graph, catalog), [graph, catalog]);
  const candidates = useMemo(
    () => sourceCandidates(graph, catalog, targetNodeId, ANY_VALUE),
    [graph, catalog, targetNodeId],
  );

  const resolve = (nodeId: Uuid, path: string[]): NodeOutputRef | null => {
    const found = candidateForField(candidates, nodeId, path);
    return found === undefined ? null : refOf(found.candidate, found.extraPath);
  };

  const commit = (text: string) => {
    if (text === "") {
      setUnknown(null);
      onRemove(targetNodeId, targetField);
      return;
    }
    const parsed = parseTemplate(text, names, resolve);
    if ("unknown" in parsed) {
      setUnknown(parsed.unknown);
      return;
    }
    setUnknown(null);
    onUpsert({
      target_node_id: targetNodeId,
      target_field: targetField,
      source: { kind: "template", parts: parsed.parts },
    });
  };

  /** Put `ref`'s placeholder at the cursor and write the result. */
  const insert = (ref: NodeOutputRef) => {
    const element = box.current as HTMLTextAreaElement;
    // At the cursor while the box is being typed in, otherwise at the end.
    const at = document.activeElement === element ? element.selectionStart : element.value.length;
    const token = placeholderText(ref.node_id, ref.field_path, names);
    element.value = `${element.value.slice(0, at)}${token}${element.value.slice(at)}`;
    commit(element.value);
  };

  const drop = (event: DragEvent) => {
    const field = droppedField(event);
    if (field === null) return;
    event.preventDefault();
    const ref = resolve(field.nodeId, field.path);
    if (ref === null) setUnknown(placeholderText(field.nodeId, field.path, names));
    else insert(ref);
  };

  const preview = template === undefined ? null : previewTemplate(template, stepData, names);
  // Shown once a run has something for at least one placeholder.
  const previewed =
    template !== undefined &&
    preview !== null &&
    preview.missing.length < outputRefs(template).length;

  return (
    // A dropped field becomes a placeholder; the Insert picker is the keyboard's way.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div className="space-y-1.5" onDrop={drop}>
      <Label htmlFor={`${idPrefix}-template`}>{label}</Label>
      <Textarea
        // Keyed by what is saved, so a write from Insert or a drop shows at once.
        key={template === undefined ? "" : templateText(template, names)}
        ref={box}
        id={`${idPrefix}-template`}
        className="font-mono text-xs"
        rows={3}
        disabled={disabled}
        // i18n-exempt: placeholder syntax shown as an example, and braces are ICU syntax in the catalog.
        placeholder="{{Form.payload.name}}"
        defaultValue={template === undefined ? "" : templateText(template, names)}
        onBlur={(event) => commit(event.target.value)}
      />
      {candidates.length > 0 && (
        <Select
          value=""
          disabled={disabled}
          onValueChange={(key) => {
            const candidate = candidateByKey(candidates, key);
            if (candidate !== undefined) insert(refOf(candidate));
          }}
        >
          <SelectTrigger
            className="h-8 w-auto text-xs"
            aria-label={t("templateInsert", { field: label })}
          >
            <SelectValue placeholder={t("templateInsertPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {candidates.map((candidate) => (
              <SelectItem key={candidate.key} value={candidate.key}>
                {placeholderText(candidate.nodeId, candidate.fieldPath, names)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
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
