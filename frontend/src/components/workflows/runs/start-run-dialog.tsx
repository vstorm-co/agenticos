"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";
import {
  type FieldProblem,
  type FormValue,
  type InputField,
  fieldCaption,
  runInputFrom,
} from "@/lib/workflows/input-fields";

interface StartRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether a published version exists to run for real. */
  canRunLive: boolean;
  /** Whether this caller may test the draft (`workflows:edit`). */
  canTest: boolean;
  busy?: boolean;
  /** What the input starts as - the draft's trigger's shape, for a test run. */
  sampleInput?: Record<string, unknown>;
  /** The fields the draft's "Manual or API" trigger declares, asked for by name in a test run. */
  testFields?: readonly InputField[];
  /** The fields the published version's trigger declares, asked for in a real run. */
  liveFields?: readonly InputField[];
  onStart: (start: { mode: "real" | "test"; input: Record<string, unknown> }) => void;
}

/** Parse the input box: a JSON object, or the message saying what is wrong. */
export function parseRunInput(text: string): Record<string, unknown> | string {
  if (text.trim() === "") return {};
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return "notObject";
    return value as Record<string, unknown>;
  } catch {
    return "notJson";
  }
}

/**
 * Start a run by hand - of the draft, to try it, or of the published version.
 *
 * The input is what the trigger hands the graph. When the trigger declares
 * fields, each is asked for by name and typed as declared - the version being
 * run decides which; otherwise it is a JSON object, typed the way an API caller
 * would send it, and prefilled in the draft trigger's shape.
 */
export function StartRunDialog({
  open,
  onOpenChange,
  canRunLive,
  canTest,
  busy,
  sampleInput = {},
  testFields = [],
  liveFields = [],
  onStart,
}: StartRunDialogProps) {
  const t = useTranslations("pages.workflows");
  const [mode, setMode] = useState<"real" | "test">(canTest ? "test" : "real");
  const [text, setText] = useState(() =>
    Object.keys(sampleInput).length > 0 ? JSON.stringify(sampleInput, null, 2) : "{\n  \n}",
  );
  const [values, setValues] = useState<Record<string, FormValue>>({});
  const [tried, setTried] = useState(false);
  const fields = mode === "test" ? testFields : liveFields;
  const typed = fields.length > 0;
  const parsed = parseRunInput(text);
  const invalid = !typed && typeof parsed === "string";
  const fromForm = runInputFrom(fields, values);
  const problems = tried && "problems" in fromForm ? fromForm.problems : {};

  const submit = () => {
    if (typed) {
      setTried(true);
      if ("input" in fromForm) onStart({ mode, input: fromForm.input });
    } else if (typeof parsed !== "string") {
      onStart({ mode, input: parsed });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("startRunTitle")}</DialogTitle>
          <DialogDescription>{t("startRunDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="run-mode">{t("startRunMode")}</Label>
            <Select value={mode} onValueChange={(value) => setMode(value as "real" | "test")}>
              <SelectTrigger id="run-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canTest && <SelectItem value="test">{t("modeTest")}</SelectItem>}
                {canRunLive && <SelectItem value="real">{t("modeReal")}</SelectItem>}
              </SelectContent>
            </Select>
          </div>
          {typed ? (
            <div className="space-y-3">
              {fields.map((field) => (
                <RunField
                  key={field.name}
                  field={field}
                  value={values[field.name]}
                  problem={problems[field.name]}
                  onChange={(value) => setValues({ ...values, [field.name]: value })}
                />
              ))}
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label>{t("startRunInput")}</Label>
              <CodeArea
                name="input.json"
                aria-label={t("startRunInput")}
                value={text}
                onChange={setText}
                className="min-h-40"
              />
              {typeof parsed === "string" && (
                <p className="text-destructive text-xs">{t(`startRunInputInvalid.${parsed}`)}</p>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={invalid || busy || (mode === "real" && !canRunLive)} onClick={submit}>
            {t("startRun")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface RunFieldProps {
  field: InputField;
  value: FormValue | undefined;
  problem: FieldProblem | undefined;
  onChange: (value: FormValue) => void;
}

/** One declared field in the Run form, as the input its type calls for. */
function RunField({ field, value, problem, onChange }: RunFieldProps) {
  const t = useTranslations("pages.workflows");
  const id = `run-field-${field.name}`;
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
