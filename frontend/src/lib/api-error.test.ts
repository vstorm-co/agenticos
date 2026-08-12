import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import pl from "../../messages/pl.json";
import type { Translate } from "./agent-step-captions";
import {
  ApiError,
  fieldProblems,
  getErrorMessage,
  parseErrorMessage,
  problemList,
  submitFailure,
} from "./api-error";
import { BFF_ERROR_KEYS } from "./bff-errors";

/**
 * The real `errors` messages, in both locales: what a refusal shows is what these
 * tests are about, and resolving them here also proves every code in
 * `BFF_ERROR_KEYS` has its copy. Cast for the reason `tool-steps.test.ts` casts.
 */
const tEn = createTranslator({ locale: "en", messages: en, namespace: "errors" }) as Translate;
const tPl = createTranslator({ locale: "pl", messages: pl, namespace: "errors" }) as Translate;

/** A domain refusal, exactly as `app_exception_handler` writes it. */
function envelope(code: string, message: string, details: Record<string, unknown> | null = null) {
  return { error: { code, message, details } };
}

/** An `ApiError` built the way `api-client.ts` builds one, from a response body. */
function apiError(status: number, body: unknown): ApiError {
  return new ApiError(status, parseErrorMessage(body), body);
}

const CONFLICT = envelope("ALREADY_EXISTS", "An agent with the handle 'support' already exists", {
  slug: "support",
});

const VALIDATION = envelope("VALIDATION_ERROR", "Some fields need fixing: spec.name", {
  fields: [{ field: "spec.name", message: "String should have at most 128 characters" }],
});

describe("parseErrorMessage", () => {
  it("reads the message out of the platform's error envelope", () => {
    // The whole point. This is what the client used to miss entirely: it looked
    // for `detail` and `message` at the top level, found neither, and every
    // refusal in the product reached the browser as "Request failed".
    expect(parseErrorMessage(CONFLICT)).toBe("An agent with the handle 'support' already exists");
  });

  it("reads the flat `detail` this app's own proxy routes produce", () => {
    expect(parseErrorMessage({ detail: "Not authenticated" })).toBe("Not authenticated");
  });

  it("reads a raw FastAPI validation body, which some routes still answer with", () => {
    expect(
      parseErrorMessage({
        detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
      }),
    ).toBe("name: Field required");
  });

  it("reads a plain `message` body, which some upstreams answer with", () => {
    expect(parseErrorMessage({ message: "Upstream provider timed out" }, "fallback")).toBe(
      "Upstream provider timed out",
    );
  });

  it("takes an envelope whose code is not a string as an unknown code", () => {
    // The envelope is still read - its message and details are what a form shows.
    // Refusing the whole thing over a malformed code would lose them.
    const error = new ApiError(400, "Refused", {
      error: { code: 7, message: "Refused", details: { slug: "support" } },
    });

    expect(error.code).toBe("UNKNOWN");
    expect(error.details).toEqual({ slug: "support" });
  });

  it("falls back rather than stringifying something it does not recognise", () => {
    // `{"detail": [...]}` passed straight to `Error` used to render as
    // "[object Object]" - a message that says nothing and looks like a crash.
    expect(parseErrorMessage(null)).toBe("Request failed");
    expect(parseErrorMessage({ error: { code: "X" } })).toBe("Request failed");
  });
});

describe("ApiError", () => {
  it("carries the code and details off the envelope", () => {
    const error = new ApiError(409, parseErrorMessage(CONFLICT), CONFLICT);
    expect(error.code).toBe("ALREADY_EXISTS");
    expect(error.details).toEqual({ slug: "support" });
  });

  it("stays usable when the body is not an envelope at all", () => {
    const error = new ApiError(502, "Request failed", "<html>gateway</html>");
    expect(error.code).toBe("UNKNOWN");
    expect(error.details).toBeNull();
  });
});

describe("problemList", () => {
  it("returns every reason the spec was refused", () => {
    const error = new ApiError(400, "This agent cannot be published yet", {
      error: {
        code: "BAD_REQUEST",
        message: "This agent cannot be published yet",
        details: { problems: ["Unknown capability: typo", "No model selected"] },
      },
    });
    expect(problemList(error)).toEqual(["Unknown capability: typo", "No model selected"]);
  });

  it("is null when the problems list holds nothing readable", () => {
    // An empty list would render as a "cannot be published" banner with no
    // reasons under it.
    const error = new ApiError(400, "…", {
      error: { code: "BAD_REQUEST", message: "…", details: { problems: [7, null] } },
    });
    expect(problemList(error)).toBeNull();
  });

  it("is null for a failure that is not a verdict on the spec", () => {
    // A 403 rendered in the "cannot be published yet" banner would blame the
    // agent for something no edit to the agent can fix.
    expect(problemList(new ApiError(403, "Insufficient permissions", null))).toBeNull();
    expect(problemList(new Error("offline"))).toBeNull();
  });
});

describe("fieldProblems", () => {
  it("reads the fields the backend's validation handler names", () => {
    expect(fieldProblems(new ApiError(422, "…", VALIDATION))).toEqual([
      { field: "spec.name", message: "String should have at most 128 characters" },
    ]);
  });

  it("falls back to a raw FastAPI body for the routes that still produce one", () => {
    const error = new ApiError(422, "…", {
      detail: [{ loc: ["body", "password"], msg: "String should have at least 8 characters" }],
    });
    expect(fieldProblems(error)).toEqual([
      { field: "password", message: "String should have at least 8 characters" },
    ]);
  });

  it("names no field for a failure that never reached the server", () => {
    expect(fieldProblems(new Error("offline"))).toEqual([]);
  });

  it("names no field for a raw body whose entries say nothing", () => {
    const error = new ApiError(422, "…", { detail: [{ loc: ["body"] }] });
    expect(fieldProblems(error)).toEqual([]);
  });

  it("skips entries that are not problems, rather than rendering junk beside a field", () => {
    // Both readers filter. A filter nobody exercises is one that can be wrong
    // for as long as the shape it guards against never arrives.
    const raw = new ApiError(422, "…", {
      detail: ["not an object", { loc: "not a list", msg: "Field required" }, { msg: 7 }],
    });
    expect(fieldProblems(raw)).toEqual([{ field: "request", message: "Field required" }]);

    const enveloped = new ApiError(
      422,
      "…",
      envelope("VALIDATION_ERROR", "…", { fields: [null, { field: "name" }, 3] }),
    );
    expect(fieldProblems(enveloped)).toEqual([]);
  });
});

describe("submitFailure", () => {
  const form = { fields: ["name", "description"], identifiedBy: "name" } as const;

  it("puts a conflict beside the field that produced the taken value", () => {
    // The reported bug, in one assertion: the handle is derived from the name,
    // so "that handle is taken" is a fact about the Name input, and belongs
    // under it rather than in a toast that vanishes.
    const failure = submitFailure(
      new ApiError(409, parseErrorMessage(CONFLICT), CONFLICT),
      form,
      tEn,
    );
    expect(failure.fields.name).toBe("An agent with the handle 'support' already exists");
    expect(failure.toast).toBeNull();
  });

  it("matches a field by its leaf, because the Builder posts a nested spec", () => {
    const failure = submitFailure(new ApiError(422, "…", VALIDATION), form, tEn);
    expect(failure.fields.name).toBe("String should have at most 128 characters");
    expect(failure.toast).toBeNull();
  });

  it("leaves a real failure loud", () => {
    // The line this must never cross: softening a 500 into a field hint would
    // tell somebody their name was wrong when the server fell over.
    const error = new ApiError(500, "An unexpected error occurred", {
      error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred", details: null },
    });
    const failure = submitFailure(error, form, tEn);
    expect(failure.fields).toEqual({});
    expect(failure.toast).toBe("An unexpected error occurred");
  });

  it("does not attribute a conflict to a form that has no single identifier", () => {
    const failure = submitFailure(
      new ApiError(409, parseErrorMessage(CONFLICT), CONFLICT),
      { fields: ["name"] },
      tEn,
    );
    expect(failure.fields).toEqual({});
    expect(failure.toast).toBe("An agent with the handle 'support' already exists");
  });

  it("toasts a problem about a field this form does not have", () => {
    // Otherwise it would be reported nowhere at all, which is worse than a
    // toast: the reader is told the save failed and never told why.
    const error = new ApiError(
      422,
      "…",
      envelope("VALIDATION_ERROR", "…", {
        fields: [{ field: "instructions", message: "String should have at most 100 characters" }],
      }),
    );
    const failure = submitFailure(error, form, tEn);
    expect(failure.fields).toEqual({});
    expect(failure.toast).toBe("instructions: String should have at most 100 characters");
  });

  it("splits a mixed rejection, showing what it can and saying the rest", () => {
    const error = new ApiError(
      422,
      "…",
      envelope("VALIDATION_ERROR", "…", {
        fields: [
          { field: "name", message: "Field required" },
          { field: "instructions", message: "String should have at most 100 characters" },
        ],
      }),
    );
    const failure = submitFailure(error, form, tEn);
    expect(failure.fields).toEqual({ name: "Field required" });
    expect(failure.toast).toBe("instructions: String should have at most 100 characters");
  });

  it("does not mistake a field for one whose name merely ends the same way", () => {
    // `spec.name` is the Name input; `spec.budget.name` is not, and matching on
    // a bare substring would mark the wrong control.
    const error = new ApiError(
      422,
      "…",
      envelope("VALIDATION_ERROR", "…", {
        fields: [{ field: "surname", message: "Field required" }],
      }),
    );
    expect(submitFailure(error, form, tEn).fields).toEqual({});
  });

  it("handles a thrown value that never reached the server", () => {
    expect(submitFailure(new TypeError("Failed to fetch"), form, tEn)).toEqual({
      fields: {},
      toast: "Failed to fetch",
    });
  });
});

describe("getErrorMessage", () => {
  it("resolves a BFF refusal code in the reader's locale (#603)", () => {
    // The regression this exists for: a BFF route cannot write a sentence, so it
    // writes a code - and the toast used to show its English detail verbatim
    // under every locale.
    const refusal = apiError(401, { code: "NOT_AUTHENTICATED" });
    expect(refusal.code).toBe("NOT_AUTHENTICATED");
    expect(getErrorMessage(refusal, tEn)).toBe("Not authenticated");
    expect(getErrorMessage(refusal, tPl)).toBe("Nie jesteś zalogowany");
  });

  it("shows the backend's own message as written, whatever its code", () => {
    const refused = apiError(409, CONFLICT);
    expect(getErrorMessage(refused, tPl)).toBe("An agent with the handle 'support' already exists");
  });

  it("does not mistake an unmapped top-level code for a BFF refusal", () => {
    const stranger = apiError(500, { code: "SOMETHING_ELSE" });
    expect(stranger.code).toBe("UNKNOWN");
    expect(getErrorMessage(stranger, tPl)).toBe("Żądanie nie powiodło się");
  });

  it("translates the fallback sentinel a body that named nothing gets", () => {
    expect(getErrorMessage(apiError(502, null), tEn)).toBe("Request failed");
    expect(getErrorMessage(apiError(502, null), tPl)).toBe("Żądanie nie powiodło się");
  });

  it("uses the error's own sentence, which is the server's refusal", () => {
    expect(getErrorMessage(new Error("Missing required permission"), tEn)).toBe(
      "Missing required permission",
    );
  });

  it("falls back for something thrown that is not an error", () => {
    // A rejected fetch can throw a string or an event; neither is worth showing.
    expect(getErrorMessage("boom", tEn)).toBe("An unexpected error occurred");
    expect(getErrorMessage("boom", tPl)).toBe("Wystąpił nieoczekiwany błąd");
    expect(getErrorMessage(undefined, tEn, "Could not save")).toBe("Could not save");
  });
});

describe("BFF_ERROR_KEYS", () => {
  it("holds copy for every code, in both catalogs", () => {
    // A code without a message would reach the toast as raw English fallback -
    // exactly the defect the table exists to end.
    for (const key of Object.values(BFF_ERROR_KEYS)) {
      expect(en.errors[key as keyof typeof en.errors]).toBeTruthy();
      expect(pl.errors[key as keyof typeof pl.errors]).toBeTruthy();
    }
  });

  it("localizes the toast a form shows for a BFF refusal", () => {
    const failure = submitFailure(
      apiError(500, { code: "INTERNAL_SERVER_ERROR" }),
      { fields: ["name"] },
      tPl,
    );
    expect(failure.toast).toBe("Wewnętrzny błąd serwera");
  });
});
