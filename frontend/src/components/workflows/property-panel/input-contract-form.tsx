"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";
import { inputSchemaOf } from "@/lib/workflows/input-fields";
import type { JsonSchema, NodeInstance, Uuid } from "@/lib/workflows/types";

import { InputFieldsForm } from "./input-fields-form";

interface InputContractFormProps {
  node: NodeInstance;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
}

const EMPTY_SCHEMA = { $schema: "https://json-schema.org/draft/2020-12/schema", type: "object" };

/** A portable input contract, or the existing simple-field editor. Forms keep their fields. */
export function InputContractForm(props: InputContractFormProps) {
  const { node, disabled, updateNodeConfig } = props;
  const t = useTranslations("workflows.inputFields");
  const schema = inputSchemaOf(node.config);
  if (node.definition_id === "trigger.form") return <InputFieldsForm {...props} />;
  return (
    <div className="space-y-3">
      <div className="space-y-1.5" data-tour="workflow-input-contract">
        <Label htmlFor="input-contract-format">{t("contractFormat")}</Label>
        <Select
          value={schema === null ? "fields" : "schema"}
          disabled={disabled}
          onValueChange={(value) => {
            if (value === "schema")
              updateNodeConfig(node.id, { ...node.config, fields: [], input_schema: EMPTY_SCHEMA });
            else updateNodeConfig(node.id, { ...node.config, input_schema: null });
          }}
        >
          <SelectTrigger id="input-contract-format">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fields">{t("simpleFields")}</SelectItem>
            <SelectItem value="schema">{t("jsonSchema")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("formatHint")}</p>
      </div>
      {schema === null ? (
        <InputFieldsForm {...props} />
      ) : (
        <InputSchemaEditor key={node.id} {...props} />
      )}
    </div>
  );
}

/** A schema being typed must parse as an object before it can replace the saved contract. */
function parseSchema(text: string): JsonSchema | null {
  try {
    return inputSchemaOf({ input_schema: JSON.parse(text) });
  } catch {
    return null;
  }
}

function InputSchemaEditor({ node, disabled, updateNodeConfig }: InputContractFormProps) {
  const t = useTranslations("workflows.inputFields");
  const schema = node.config["input_schema"];
  const saved = JSON.stringify(schema);
  const [draft, setDraft] = useState(() => ({ saved, text: JSON.stringify(schema, null, 2) }));
  const parsed = parseSchema(draft.text);
  if (draft.saved !== saved) {
    // Undo and version restores replace the editor's contents; an own save keeps
    // the author's spacing and caret because it represents the same schema.
    setDraft({
      saved,
      text: JSON.stringify(parsed) === saved ? draft.text : JSON.stringify(schema, null, 2),
    });
  }
  return (
    <div className="space-y-1.5">
      <Label htmlFor="trigger-input-schema">{t("jsonSchema")}</Label>
      <p className="text-muted-foreground text-xs">{t("schemaHint")}</p>
      <CodeArea
        id="trigger-input-schema"
        name="input-schema.json"
        aria-label={t("jsonSchema")}
        value={draft.text}
        disabled={disabled}
        invalid={parsed === null}
        className="min-h-48"
        onChange={(next) => {
          setDraft({ saved, text: next });
          const value = parseSchema(next);
          if (value !== null)
            updateNodeConfig(node.id, { ...node.config, fields: [], input_schema: value });
        }}
      />
      {parsed === null && <p className="text-destructive text-xs">{t("schemaInvalid")}</p>}
    </div>
  );
}
