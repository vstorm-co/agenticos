"use client";

import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { RunField } from "@/components/workflows/runs/run-field";
import {
  type FieldProblem,
  type FormValue,
  type InputField,
  initialValues,
  runInputFrom,
  serverFieldProblems,
} from "@/lib/workflows/input-fields";

/** What a workflow's public form shows - `WorkflowFormPage`. */
export interface PublicFormPage {
  title: string;
  description: string | null;
  submit_label: string;
  fields: InputField[];
}

/** Why the form could not take the answers, as the page says it. */
type Refusal =
  "invalid" | "changed" | "unreadable" | "tooLarge" | "busy" | "unavailable" | "gone" | "failed";

function refusalOf(status: number): Refusal {
  if (status === 429) return "busy";
  // The workflow's monthly budget is spent: nothing the visitor can do about it.
  if (status === 402) return "unavailable";
  if (status === 404) return "gone";
  if (status === 413) return "tooLarge";
  return "failed";
}

/** The `details` of the API's error envelope, or an empty object for a body that is not one. */
async function detailsOf(response: Response): Promise<Record<string, unknown>> {
  try {
    const body = (await response.json()) as { error?: { details?: unknown } };
    const details = body.error?.details;
    return typeof details === "object" && details !== null
      ? (details as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/**
 * A workflow's form, filled in by somebody with its link.
 *
 * Checked here first, as the Run form checks its fields, so a missing answer is
 * named before anything is sent; the API checks again and starts the run. The
 * `website` box is out of sight and out of the tab order: a person leaves it
 * empty, and the API thanks a submission that fills it in without starting anything.
 */
export function PublicForm({ page, token }: { page: PublicFormPage; token: string }) {
  const t = useTranslations("publicForm");
  const [values, setValues] = useState<Record<string, FormValue>>(() => initialValues(page.fields));
  const [website, setWebsite] = useState("");
  const [tried, setTried] = useState(false);
  const [sending, setSending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [serverProblems, setServerProblems] = useState<Record<string, FieldProblem>>({});
  const [thanks, setThanks] = useState<string | null>(null);

  const answers = runInputFrom(page.fields, values);
  const problems: Record<string, FieldProblem> =
    tried && "problems" in answers ? answers.problems : {};

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setTried(true);
    if (!("input" in answers)) return;
    setSending(true);
    setRefusal(null);
    setServerProblems({});
    try {
      const response = await fetch(`/api/forms/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: answers.input, website: website || null }),
      });
      if (response.ok) {
        const body = (await response.json()) as { message: string };
        setThanks(body.message);
      } else if (response.status === 422) {
        const details = await detailsOf(response);
        if (Array.isArray(details.fields)) {
          setRefusal("unreadable");
        } else {
          const refused = serverFieldProblems(details.problems, page.fields);
          setServerProblems(refused.problems);
          setRefusal(refused.changed ? "changed" : "invalid");
        }
      } else {
        setRefusal(refusalOf(response.status));
      }
    } catch {
      setRefusal("failed");
    } finally {
      setSending(false);
    }
  };

  if (thanks !== null) {
    return (
      <div className="space-y-3 py-6 text-center" role="status">
        <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" aria-hidden="true" />
        <p className="text-base">{thanks}</p>
      </div>
    );
  }

  return (
    <form className="space-y-6" onSubmit={submit} noValidate>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{page.title}</h1>
        {page.description !== null && (
          <p className="text-muted-foreground text-sm whitespace-pre-line">{page.description}</p>
        )}
      </header>
      <div className="space-y-4">
        {page.fields.map((field) => (
          <RunField
            key={field.name}
            field={field}
            value={values[field.name]}
            problem={problems[field.name] ?? serverProblems[field.name]}
            onChange={(value) => {
              setValues({ ...values, [field.name]: value });
              if (field.name in serverProblems) {
                const { [field.name]: _cleared, ...rest } = serverProblems;
                setServerProblems(rest);
              }
            }}
          />
        ))}
      </div>
      <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
        <label htmlFor="form-website">{t("trapLabel")}</label>
        <input
          id="form-website"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(event) => setWebsite(event.target.value)}
        />
      </div>
      {refusal !== null && (
        <p className="text-destructive text-sm" role="alert">
          {t(`refused.${refusal}`)}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={sending}>
        {sending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {page.submit_label}
      </Button>
    </form>
  );
}
