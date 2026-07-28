/**
 * What a refused request looks like, and where its parts belong on screen.
 *
 * The backend answers every refusal in one envelope:
 *
 *     {"error": {"code": ..., "message": ..., "details": ...}}
 *
 * and `platform-proxy.ts` passes it through byte for byte. Nothing here used to
 * read it: the client looked for `detail` and `message` at the top level, found
 * neither, and fell back to "Request failed" - so a duplicate name, a refused
 * permission and an unpublished agent all reached the browser as the same three
 * words, and every carefully written server message died in transit.
 *
 * Two further shapes exist and are not going away, so this module knows all
 * three: `{"detail": "..."}` from this app's own BFF routes (`Not
 * authenticated`) and from Starlette's `HTTPException`, and `{"detail": [...]}`
 * from any FastAPI validation the backend's handler does not reach.
 *
 * The other half of the job is deciding *where* a problem goes. A conflict on a
 * name and a rejected length are things a person can fix in the form they are
 * already looking at; a 403 or a 500 is not. `submitFailure` splits one from
 * the other, and it is deliberately the only thing that makes that call - a
 * form that decided for itself would eventually decide differently.
 */

import { getErrorMessage } from "@/lib/utils";

/** A problem the server attributed to a named field. */
export type FieldProblem = {
  /** Dotted path below the request body, e.g. `name` or `spec.capabilities.2.id`. */
  readonly field: string;
  readonly message: string;
};

/** What is left of a rejected submission once each part has found its place. */
export type SubmitFailure = {
  /** Messages to render beside the inputs the form owns, keyed by field name. */
  readonly fields: Readonly<Record<string, string>>;
  /**
   * Everything with nowhere better to go - a refused permission, a server
   * fault, a lost connection. `null` when every problem found a field, which is
   * the whole point: an expected, recoverable, field-shaped failure must not
   * also be announced as if something broke.
   */
  readonly toast: string | null;
};

const FALLBACK_MESSAGE = "Request failed";
const UNKNOWN_CODE = "UNKNOWN";

type Envelope = { code: string; message: string; details: Record<string, unknown> | null };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The `{"error": {...}}` envelope, or null if the body is not one. */
function readEnvelope(body: unknown): Envelope | null {
  if (!isRecord(body) || !isRecord(body.error)) return null;
  const { code, message, details } = body.error;
  if (typeof message !== "string") return null;
  return {
    code: typeof code === "string" ? code : UNKNOWN_CODE,
    message,
    details: isRecord(details) ? details : null,
  };
}

/** FastAPI's own validation shape, for the routes our handler does not cover. */
function readFastApiDetail(body: unknown): FieldProblem[] | null {
  if (!isRecord(body) || !Array.isArray(body.detail)) return null;
  const problems: FieldProblem[] = [];
  for (const entry of body.detail) {
    if (!isRecord(entry) || typeof entry.msg !== "string") continue;
    const location = Array.isArray(entry.loc) ? entry.loc.slice(1) : [];
    problems.push({ field: location.join(".") || "request", message: entry.msg });
  }
  return problems.length > 0 ? problems : null;
}

/**
 * The sentence to show for a rejected response body.
 *
 * Exported for `api-client.ts`, which needs it before an `ApiError` exists.
 */
export function parseErrorMessage(body: unknown, fallback: string = FALLBACK_MESSAGE): string {
  const envelope = readEnvelope(body);
  if (envelope) return envelope.message;

  const problems = readFastApiDetail(body);
  if (problems) return problems.map((problem) => `${problem.field}: ${problem.message}`).join("; ");

  if (isRecord(body)) {
    if (typeof body.detail === "string") return body.detail;
    if (typeof body.message === "string") return body.message;
  }
  return fallback;
}

/**
 * A failed request, carrying enough of the response to act on it.
 *
 * `code` and `details` are read off the body once, here, so no caller has to
 * know which of the three wire shapes it was handed.
 */
export class ApiError extends Error {
  /** The backend's machine-readable code, e.g. `ALREADY_EXISTS`. */
  readonly code: string;
  /** The refusal's structured payload - field problems, spec problems, ids. */
  readonly details: Record<string, unknown> | null;

  constructor(
    public status: number,
    public message: string,
    public data?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    const envelope = readEnvelope(data);
    this.code = envelope?.code ?? UNKNOWN_CODE;
    this.details = envelope?.details ?? null;
  }
}

/** Every field the server named as wrong. Empty when it named none. */
export function fieldProblems(error: unknown): FieldProblem[] {
  if (!(error instanceof ApiError)) return [];

  const fields = error.details?.fields;
  if (Array.isArray(fields)) {
    return fields.filter(
      (problem): problem is FieldProblem =>
        isRecord(problem) &&
        typeof problem.field === "string" &&
        typeof problem.message === "string",
    );
  }
  return readFastApiDetail(error.data) ?? [];
}

/**
 * Every reason a spec was refused, when the server reported them together.
 *
 * `validate_spec` deliberately collects all of them before raising, so that
 * fixing a form costs one round trip rather than one per mistake. Returns null
 * when the failure was not that kind - a 403 is not a list of problems, and
 * showing it as one would say the spec is wrong when the caller is.
 */
export function problemList(error: unknown): string[] | null {
  if (!(error instanceof ApiError)) return null;
  const problems = error.details?.problems;
  if (!Array.isArray(problems)) return null;
  const strings = problems.filter((problem): problem is string => typeof problem === "string");
  return strings.length > 0 ? strings : null;
}

/**
 * Does this field problem belong to `owned`?
 *
 * A path is matched by its leaf as well as in full, because the Builder posts
 * its whole spec under one key: the server says `spec.name` about the input the
 * form calls `name`.
 */
function matches(problem: FieldProblem, owned: string): boolean {
  return problem.field === owned || problem.field.endsWith(`.${owned}`);
}

/** What a form can show, so `submitFailure` knows where each problem goes. */
export type FormShape = {
  /** Every input the form renders, by field name. */
  readonly fields: readonly string[];
  /**
   * The one field the resource is identified by - the name, the label, the
   * slug - if there is one.
   *
   * A conflict cannot be routed any other way: the server reports that a
   * *handle* is taken, which is a fact about a value the form holds under a
   * different name, and it has no way to know what this form calls it. Naming
   * it here is what lets "that handle is taken" land under the input that
   * produced the handle. Omit it and a conflict falls back to a toast, which
   * is honest rather than a guess.
   */
  readonly identifiedBy?: string;
};

/**
 * Split a rejected submission into what the form can show and what it cannot.
 *
 * Anything the server blames on a field the form renders is returned to be
 * shown there; everything else - a refused permission, a server fault, a
 * problem about a field this form does not have - comes back as one line for a
 * toast, because pretending otherwise would leave a failure invisible.
 */
export function submitFailure(error: unknown, form: FormShape): SubmitFailure {
  if (!(error instanceof ApiError)) {
    return { fields: {}, toast: getErrorMessage(error) };
  }

  if (error.status === 409) {
    return form.identifiedBy === undefined
      ? { fields: {}, toast: error.message }
      : { fields: { [form.identifiedBy]: error.message }, toast: null };
  }

  const problems = fieldProblems(error);
  if (problems.length === 0) {
    return { fields: {}, toast: error.message };
  }

  const fields: Record<string, string> = {};
  const orphans: string[] = [];
  for (const problem of problems) {
    const field = form.fields.find((candidate) => matches(problem, candidate));
    // Last one wins, so the input shows the problem the server listed last -
    // arbitrary, but an input can only say one thing and two problems about one
    // value is not something the backend produces.
    if (field === undefined) orphans.push(`${problem.field}: ${problem.message}`);
    else fields[field] = problem.message;
  }

  return { fields, toast: orphans.length > 0 ? orphans.join("; ") : null };
}
