import { ApiError } from "@/lib/api-error";
import {
  BROWSER_PROCEDURE_TEACHING_REASONS,
  type BrowserProcedureTeaching,
  type BrowserProcedureTeachingReason,
  type BrowserProcedureTeachingReview,
} from "@/types/browser-procedure-teaching";

export const BROWSER_PROCEDURE_TEACHING_POLL_MS = 2_000;
export const BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS = 180_000;
export const isBrowserProcedureTeachingId = (id: string) =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
export const browserProcedureTeachingDeadlineLive = (value: string, now = Date.now()) =>
  Number.isFinite(Date.parse(value)) && Date.parse(value) > now;
export const browserProcedureTeachingDraftPending = (value: BrowserProcedureTeaching | undefined) =>
  value?.generation_state === "queued" || value?.generation_state === "generating";
export function browserProcedureTeachingReason(
  error: unknown,
): BrowserProcedureTeachingReason | null {
  if (!(error instanceof ApiError)) return null;
  const value = error.details?.reason_code;
  return typeof value === "string" &&
    (BROWSER_PROCEDURE_TEACHING_REASONS as readonly string[]).includes(value)
    ? (value as BrowserProcedureTeachingReason)
    : null;
}
export function browserProcedureTeachingOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.hostname.endsWith("."))
      return null;
    return url.origin;
  } catch {
    return null;
  }
}
/** Admission accepts canonical HTTPS origins, not a page URL or wildcard. */
export function browserProcedureTeachingOrigins(value: string): string[] | null {
  const values = value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!values.length || values.length > 10 || new Set(values).size !== values.length) return null;
  return values.every((item) => browserProcedureTeachingOrigin(item) === item) ? values : null;
}
export function initialBrowserProcedureTeachingReview(
  session: BrowserProcedureTeaching,
): BrowserProcedureTeachingReview {
  if (session.review) return structuredClone(session.review);
  return {
    name: "",
    description: "",
    actions: session.events.map((event) => ({
      sequence: event.sequence,
      label: "",
      parameter: null,
      path_template: null,
      omit: false,
    })),
    parameters: [],
    prerequisites: [],
    success_checks: [""],
  };
}
export type BrowserProcedureTeachingReviewIssue =
  | "name"
  | "description"
  | "sequence"
  | "parameters"
  | "label"
  | "parameter"
  | "path"
  | "keptStep"
  | "prerequisites"
  | "successChecks";
const textWithin = (value: string, max: number) => value.trim().length > 0 && value.length <= max;
const parameterName = (value: string) => /^[a-z][a-z0-9_]{0,31}$/.test(value);
export function browserProcedureTeachingPathValid(
  value: string,
  parameters: ReadonlySet<string>,
): boolean {
  if (
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.length > 512 ||
    /[?#%\\:@\u0000-\u001f\u007f]/.test(value) ||
    value.split("/").some((part) => part === "." || part === "..")
  )
    return false;
  const placeholders = [...value.matchAll(/\{([a-z][a-z0-9_]{0,31})\}/g)];
  const stripped = value.replace(/\{[a-z][a-z0-9_]{0,31}\}/g, "");
  return !/[{}]/.test(stripped) && placeholders.every((match) => parameters.has(match[1]!));
}
/** Validate the complete review, retaining every sequence even when explicitly omitted. */
export function browserProcedureTeachingReviewIssue(
  session: BrowserProcedureTeaching,
  review: BrowserProcedureTeachingReview,
): BrowserProcedureTeachingReviewIssue | null {
  if (review.name.length > 64 || !/^[a-z0-9][a-z0-9_-]*$/.test(review.name)) return "name";
  if (!textWithin(review.description, 500)) return "description";
  if (
    !session.events.length ||
    review.actions.length > 500 ||
    review.actions.length !== session.events.length ||
    review.actions.some(
      (item, i) =>
        !Number.isInteger(item.sequence) ||
        item.sequence < 1 ||
        item.sequence > 500 ||
        item.sequence !== session.events[i]!.sequence ||
        (i > 0 && item.sequence <= review.actions[i - 1]!.sequence),
    )
  )
    return "sequence";
  const names = new Set(review.parameters.map((item) => item.name));
  if (
    review.parameters.length > 50 ||
    names.size !== review.parameters.length ||
    review.parameters.some(
      (item) => !parameterName(item.name) || !textWithin(item.description, 240),
    )
  )
    return "parameters";
  for (let i = 0; i < review.actions.length; i++) {
    const step = review.actions[i]!;
    const event = session.events[i]!;
    if (!textWithin(step.label, 160)) return "label";
    // The closed review schema validates optional fields even on omitted steps.
    if (step.parameter !== null && (!parameterName(step.parameter) || !names.has(step.parameter)))
      return "parameter";
    if (
      step.path_template !== null &&
      !browserProcedureTeachingPathValid(step.path_template, names)
    )
      return "path";
    if (step.omit) continue;
    const parameter = event.action === "input_parameter" || event.action === "select";
    if (parameter ? step.parameter === null : step.parameter !== null) return "parameter";
    if (event.action === "navigate" ? step.path_template === null : step.path_template !== null)
      return "path";
  }
  if (review.actions.every((item) => item.omit)) return "keptStep";
  if (
    review.prerequisites.length > 16 ||
    review.prerequisites.some((item) => !textWithin(item, 240))
  )
    return "prerequisites";
  if (
    !review.success_checks.length ||
    review.success_checks.length > 16 ||
    review.success_checks.some((item) => !textWithin(item, 240))
  )
    return "successChecks";
  return null;
}
export function browserProcedureTeachingBudgetValid(value: string): boolean {
  return (
    /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$/.test(value) && Number(value) > 0 && Number(value) <= 10
  );
}
