"use client";

import { useState } from "react";
import { Braces, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";

import {
  ANSWER_FIELD_TYPES,
  FIRST_FIELD,
  fieldsOf,
  parseSchema,
  schemaOf,
  type AnswerField,
  type AnswerFieldType,
} from "./answer-format";

interface AnswerFormatFormProps {
  /** The spec's `output_schema`: null for a free-text answer. */
  value: Record<string, unknown> | null;
  onChange: (value: Record<string, unknown> | null) => void;
  disabled?: boolean;
  /**
   * For a workflow step, where no schema means the agent's own answer format
   * rather than prose: the first choice is named that way instead.
   */
  keepsOwn?: boolean;
}

/**
 * How the agent answers: in prose, or with an object of named fields.
 *
 * The fields are the everyday way to say it - a name, a type, a line on what
 * goes there, whether it must be there - and they write the JSON Schema the
 * spec stores. **Edit as JSON** opens the schema itself for anything the list
 * cannot say (nested objects, enums), and a schema that already says more than
 * the list can is opened that way, so nothing it holds is dropped.
 */
export function AnswerFormatForm({ value, onChange, disabled, keepsOwn }: AnswerFormatFormProps) {
  const t = useTranslations("answerFormat");
  // The rows, kept here rather than read back off the schema: a row with no
  // name yet is not in the schema, and would vanish as it was added.
  const [fields, setRows] = useState<AnswerField[]>(
    () => (value === null ? null : fieldsOf(value)) ?? [FIRST_FIELD],
  );
  const [asJson, setAsJson] = useState(value !== null && fieldsOf(value) === null);
  const [text, setText] = useState(() => JSON.stringify(value ?? schemaOf([FIRST_FIELD]), null, 2));
  const parsed = parseSchema(text);
  const readable = typeof parsed === "string" ? null : fieldsOf(parsed);

  const setFields = (next: AnswerField[]) => {
    setRows(next);
    onChange(schemaOf(next));
  };
  const setField = (index: number, patch: Partial<AnswerField>) =>
    setFields(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)));
  const changeText = (next: string) => {
    setText(next);
    const schema = parseSchema(next);
    if (typeof schema !== "string") onChange(schema);
  };
  const openJson = () => {
    setText(JSON.stringify(value ?? schemaOf([FIRST_FIELD]), null, 2));
    setAsJson(true);
  };

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="answer-format">{t("label")}</Label>
        <Select
          value={value === null ? "text" : "structured"}
          disabled={disabled}
          onValueChange={(mode) => {
            if (mode === "text") {
              onChange(null);
              setAsJson(false);
            } else {
              setFields([FIRST_FIELD]);
            }
          }}
        >
          <SelectTrigger id="answer-format">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="text">{keepsOwn ? t("agentsOwn") : t("text")}</SelectItem>
            <SelectItem value="structured">{t("structured")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">
          {value !== null ? t("structuredHint") : keepsOwn ? t("agentsOwnHint") : t("textHint")}
        </p>
      </div>

      {value !== null && asJson && (
        <div className="space-y-1.5">
          <Label>{t("schema")}</Label>
          <CodeArea
            name="answer.schema.json"
            aria-label={t("schema")}
            value={text}
            onChange={changeText}
            readOnly={disabled}
            className="min-h-40"
          />
          {typeof parsed === "string" && (
            <p className="text-destructive text-xs">{t(`invalid.${parsed}`)}</p>
          )}
          {readable !== null && (
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => {
                setRows(readable);
                setAsJson(false);
              }}
            >
              {t("editAsFields")}
            </Button>
          )}
        </div>
      )}

      {value !== null && !asJson && (
        <div className="space-y-3">
          {fields.map((field, index) => (
            <div key={index} className="space-y-2 rounded-lg border p-3">
              <div className="grid grid-cols-[1fr_9rem_auto] items-end gap-2">
                <div className="space-y-1">
                  <Label htmlFor={`answer-field-${index}`}>{t("fieldName")}</Label>
                  <Input
                    id={`answer-field-${index}`}
                    value={field.name}
                    disabled={disabled}
                    className="font-mono"
                    onChange={(event) => setField(index, { name: event.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`answer-type-${index}`}>{t("fieldType")}</Label>
                  <Select
                    value={field.type}
                    disabled={disabled}
                    onValueChange={(type) => setField(index, { type: type as AnswerFieldType })}
                  >
                    <SelectTrigger id={`answer-type-${index}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ANSWER_FIELD_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {t(`types.${type}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("removeField", { name: field.name || index + 1 })}
                  disabled={disabled || fields.length === 1}
                  onClick={() => setFields(fields.filter((_, i) => i !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <Input
                aria-label={t("fieldDescription", { name: field.name || index + 1 })}
                placeholder={t("fieldDescriptionPlaceholder")}
                value={field.description}
                disabled={disabled}
                onChange={(event) => setField(index, { description: event.target.value })}
              />
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={field.required}
                  disabled={disabled}
                  onCheckedChange={(checked) => setField(index, { required: checked === true })}
                />
                {t("fieldRequired")}
              </label>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() =>
                setFields([
                  ...fields,
                  { name: "", type: "string", description: "", required: false },
                ])
              }
            >
              <Plus className="h-4 w-4" />
              {t("addField")}
            </Button>
            <Button variant="ghost" size="sm" disabled={disabled} onClick={openJson}>
              <Braces className="h-4 w-4" />
              {t("editAsJson")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
