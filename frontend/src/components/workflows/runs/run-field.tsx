"use client";

import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import {
  type FieldProblem,
  type FormValue,
  type InputField,
  fieldCaption,
} from "@/lib/workflows/input-fields";

interface RunFieldProps {
  field: InputField;
  idPrefix?: string;
  value: FormValue | undefined;
  problem: FieldProblem | undefined;
  onChange: (value: FormValue) => void;
}

/**
 * One declared field, as the input its type calls for - in the Run form, and on
 * a Form trigger's public page.
 */
export function RunField({
  field,
  value,
  problem,
  onChange,
  idPrefix = "run-field",
}: RunFieldProps) {
  const t = useTranslations("pages.workflows");
  const id = `${idPrefix}-${field.name}`;
  const caption = fieldCaption(field);
  const text = typeof value === "string" ? value : "";

  if (field.type === "boolean") {
    return (
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <Label htmlFor={id}>{caption}</Label>
          {field.description !== null && (
            <p className="text-muted-foreground text-xs">{field.description}</p>
          )}
        </div>
        <Switch id={id} checked={value === true} onCheckedChange={onChange} />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="flex items-baseline gap-1.5">
        {caption}
        {!field.required && (
          <span className="text-muted-foreground text-xs font-normal">{t("startRunOptional")}</span>
        )}
      </Label>
      {field.type === "choice" ? (
        <Select value={text} onValueChange={onChange}>
          <SelectTrigger id={id} aria-invalid={problem !== undefined}>
            <SelectValue placeholder={t("startRunChoose")} />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id={id}
          type={field.type === "date" ? "date" : field.type === "text" ? "text" : "number"}
          inputMode={
            field.type === "integer" ? "numeric" : field.type === "number" ? "decimal" : undefined
          }
          step={field.type === "number" ? "any" : undefined}
          aria-invalid={problem !== undefined}
          value={text}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {field.description !== null && (
        <p className="text-muted-foreground text-xs">{field.description}</p>
      )}
      {problem !== undefined && (
        <p className="text-destructive text-xs">{t(`startRunFieldProblem.${problem}`)}</p>
      )}
    </div>
  );
}
