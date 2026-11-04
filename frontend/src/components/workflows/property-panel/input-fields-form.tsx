"use client";

import { Plus, Trash2 } from "lucide-react";
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
  Textarea,
} from "@/components/ui";
import {
  FIELD_NAME,
  INPUT_FIELD_TYPES,
  type InputField,
  type InputFieldType,
  MAX_FIELDS,
  MAX_OPTIONS,
  inputFieldsOf,
} from "@/lib/workflows/input-fields";
import type { NodeInstance, Uuid } from "@/lib/workflows/types";

interface InputFieldsFormProps {
  node: NodeInstance;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
}

/** What is wrong with one field's name, among the names before it. */
function nameProblem(field: InputField, earlier: readonly InputField[]): string | null {
  if (!FIELD_NAME.test(field.name)) return "nameInvalid";
  if (earlier.some((other) => other.name === field.name)) return "nameTaken";
  return null;
}

/** The first `field_<n>` name no field has yet. */
function freshName(fields: readonly InputField[]): string {
  const taken = new Set(fields.map((field) => field.name));
  let n = fields.length + 1;
  while (taken.has(`field_${n}`)) n += 1;
  return `field_${n}`;
}

/** The options a choice offers, one per line, blank lines dropped. */
function optionsOf(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/**
 * The "Manual or API" trigger's typed input: the fields a run starts with.
 *
 * With none, a run takes any JSON object. With some, each is asked for by name
 * in the Run dialog, a run whose input does not fit is refused at the start, and
 * a later step binds `payload.<name>` knowing its type. Every edit is written as
 * typed; what cannot be published is marked on its row, and publishing names it
 * again.
 */
export function InputFieldsForm({ node, disabled, updateNodeConfig }: InputFieldsFormProps) {
  const t = useTranslations("workflows.inputFields");
  const fields = inputFieldsOf(node.config);

  const write = (next: InputField[]) => updateNodeConfig(node.id, { ...node.config, fields: next });
  const setField = (index: number, patch: Partial<InputField>) =>
    write(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)));

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <Label>{t("title")}</Label>
        <p className="text-muted-foreground text-xs">
          {fields.length === 0 ? t("noneHint") : t("someHint")}
        </p>
      </div>
      {fields.map((field, index) => {
        const problem = nameProblem(field, fields.slice(0, index));
        const caption = field.name || String(index + 1);
        return (
          <div key={index} className="space-y-2 rounded-lg border p-3">
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor={`input-field-${index}`}>{t("name")}</Label>
                <Input
                  id={`input-field-${index}`}
                  value={field.name}
                  disabled={disabled}
                  className="font-mono"
                  aria-invalid={problem !== null}
                  onChange={(event) => setField(index, { name: event.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`input-type-${index}`}>{t("type")}</Label>
                <Select
                  value={field.type}
                  disabled={disabled}
                  onValueChange={(type) =>
                    setField(index, {
                      type: type as InputFieldType,
                      options: type === "choice" ? field.options : [],
                    })
                  }
                >
                  <SelectTrigger id={`input-type-${index}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INPUT_FIELD_TYPES.map((type) => (
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
                aria-label={t("remove", { name: caption })}
                disabled={disabled}
                onClick={() => write(fields.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            {problem !== null && <p className="text-destructive text-xs">{t(problem)}</p>}
            <Input
              aria-label={t("label", { name: caption })}
              placeholder={t("labelPlaceholder")}
              value={field.label ?? ""}
              disabled={disabled}
              onChange={(event) => setField(index, { label: event.target.value || null })}
            />
            <Input
              aria-label={t("description", { name: caption })}
              placeholder={t("descriptionPlaceholder")}
              value={field.description ?? ""}
              disabled={disabled}
              onChange={(event) => setField(index, { description: event.target.value || null })}
            />
            {field.type === "choice" && (
              <div className="space-y-1">
                <Textarea
                  // Uncontrolled, so a blank line can be typed; remounted when a
                  // row above it goes, so it shows its own row's options.
                  key={`${index}-${fields.length}`}
                  aria-label={t("options", { name: caption })}
                  placeholder={t("optionsPlaceholder")}
                  defaultValue={field.options.join("\n")}
                  disabled={disabled}
                  rows={3}
                  onChange={(event) => setField(index, { options: optionsOf(event.target.value) })}
                />
                {field.options.length === 0 && (
                  <p className="text-destructive text-xs">{t("optionsNone")}</p>
                )}
                {field.options.length > MAX_OPTIONS && (
                  <p className="text-destructive text-xs">
                    {t("optionsTooMany", { max: MAX_OPTIONS })}
                  </p>
                )}
              </div>
            )}
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={field.required}
                  disabled={disabled}
                  onCheckedChange={(checked) => setField(index, { required: checked === true })}
                />
                {t("required")}
              </label>
              {problem === null && (
                <code className="text-muted-foreground font-mono text-xs">
                  {/* i18n-exempt: the binding path a later step reads, not copy */}
                  {`payload.${field.name}`}
                </code>
              )}
            </div>
          </div>
        );
      })}
      <Button
        variant="outline"
        size="sm"
        disabled={disabled || fields.length >= MAX_FIELDS}
        onClick={() =>
          write([
            ...fields,
            {
              name: freshName(fields),
              label: null,
              type: "text",
              required: true,
              description: null,
              options: [],
            },
          ])
        }
      >
        <Plus className="h-4 w-4" />
        {t("add")}
      </Button>
    </section>
  );
}
