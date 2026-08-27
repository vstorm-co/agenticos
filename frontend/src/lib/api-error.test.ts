import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

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
import { INGESTION_FORM_FIELDS } from "./ingestion-config";

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

  it("spells a BFF code out, for a reader with no translator in reach (#655)", () => {
    expect(parseErrorMessage({ code: "NOT_AUTHENTICATED" })).toBe("Not authenticated");
    expect(parseErrorMessage({ code: "SOMETHING_ELSE" })).toBe("Request failed");
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

/**
 * The three refusals a service raises for a document a route's schema cannot
 * validate, each body copied from the backend test that pins it: an ingestion
 * override (`tests/api/test_ingestion_override_routes.py`), a hand-edited spec
 * (`tests/api/test_agent_spec_import_refusal.py`) and a capability's config
 * blob (`tests/test_capability_registry.py`).
 *
 * All three are `BAD_REQUEST`, not the 422 the validation handler answers, and
 * all three used to carry Pydantic's own error list under `details.errors` -
 * which this module reads nowhere, so each one showed a sentence and marked no
 * input at all (#882). They are here rather than in the reader's own describe
 * block because what is being tested is that the wire shape reaches a form.
 */
const OVERRIDE_REFUSED = envelope(
  "BAD_REQUEST",
  "The 'ingestion' field is not a valid override for this collection",
  {
    fields: [
      {
        field: "ingestion_config",
        message: "Value error, chunk_overlap (4096) must be smaller than chunk_size (512)",
      },
    ],
  },
);

const SPEC_REFUSED = envelope("BAD_REQUEST", "This spec does not match the agent spec format", {
  fields: [{ field: "instrucitons", message: "Extra inputs are not permitted" }],
});

const CONFIG_REFUSED = envelope("BAD_REQUEST", "Invalid configuration for capability 'knowledge'", {
  capability_id: "knowledge",
  fields: [{ field: "default_top_k", message: "Input should be less than or equal to 50" }],
});

describe("a refusal a service raised about a document it validated itself", () => {
  it("names the setting a rejected ingestion override is about", () => {
    // A `model_validator` names neither of the two settings it is about, so the
    // server attributes the pair to the object - the field `IngestionSettings`
    // reserves for exactly this rule.
    expect(fieldProblems(apiError(400, OVERRIDE_REFUSED))).toEqual([
      {
        field: "ingestion_config",
        message: "Value error, chunk_overlap (4096) must be smaller than chunk_size (512)",
      },
    ]);
  });

  it("marks the ingestion input the refusal names, and stays out of the toast", () => {
    const failure = submitFailure(
      apiError(400, OVERRIDE_REFUSED),
      { fields: [...INGESTION_FORM_FIELDS] },
      tEn,
    );

    expect(failure.fields.ingestion_config).toBe(
      "Value error, chunk_overlap (4096) must be smaller than chunk_size (512)",
    );
    expect(failure.toast).toBeNull();
  });

  it("names the key a hand-edited spec misspelled", () => {
    expect(fieldProblems(apiError(400, SPEC_REFUSED))).toEqual([
      { field: "instrucitons", message: "Extra inputs are not permitted" },
    ]);
  });

  it("marks the config input a capability refused, and keeps the capability it is about", () => {
    const error = apiError(400, CONFIG_REFUSED);
    const failure = submitFailure(error, { fields: ["default_top_k"] }, tEn);

    expect(failure.fields.default_top_k).toBe("Input should be less than or equal to 50");
    expect(failure.toast).toBeNull();
    // Which card to open it on. The Builder posts every binding at once, so the
    // field alone does not say which capability was refused.
    expect(error.details?.capability_id).toBe("knowledge");
  });
});

describe("a refusal a service states in prose about one input", () => {
  /**
   * Bodies copied out of the backend's own tests. Eighteen of these answered a
   * singular `details.field` with the sentence on the envelope, which this
   * module reads nowhere - so each showed a toast and marked nothing (#891).
   */
  const ENDPOINT_REFUSED = envelope(
    "BAD_REQUEST",
    "A model endpoint must be an http or https URL",
    {
      fields: [{ field: "base_url", message: "A model endpoint must be an http or https URL" }],
    },
  );

  const MCP_URL_REFUSED = envelope(
    "BAD_REQUEST",
    "This MCP server URL cannot be used: loopback addresses are not reachable",
    {
      fields: [
        {
          field: "url",
          message: "This MCP server URL cannot be used: loopback addresses are not reachable",
        },
      ],
    },
  );

  const YAML_REFUSED = envelope("BAD_REQUEST", "This spec is not valid YAML - line 2, column 14", {
    fields: [{ field: "yaml", message: "This spec is not valid YAML - line 2, column 14" }],
  });

  it("marks the endpoint a model profile was refused over", () => {
    const failure = submitFailure(apiError(400, ENDPOINT_REFUSED), { fields: ["base_url"] }, tEn);

    expect(failure.fields.base_url).toBe("A model endpoint must be an http or https URL");
    expect(failure.toast).toBeNull();
  });

  it("marks the server URL an MCP connection was refused over", () => {
    expect(fieldProblems(apiError(400, MCP_URL_REFUSED))).toEqual([
      {
        field: "url",
        message: "This MCP server URL cannot be used: loopback addresses are not reachable",
      },
    ]);
  });

  it("carries the position of a spec that never parsed in the sentence it marks with", () => {
    // The line and column used to be `details` keys of their own that nothing
    // read; they are only worth reporting to the reader who has the document.
    expect(fieldProblems(apiError(400, YAML_REFUSED))).toEqual([
      { field: "yaml", message: "This spec is not valid YAML - line 2, column 14" },
    ]);
  });

  it("says one thing once - the field, and no toast repeating it", () => {
    const failure = submitFailure(apiError(400, ENDPOINT_REFUSED), { fields: ["base_url"] }, tEn);

    expect(Object.keys(failure.fields)).toEqual(["base_url"]);
    expect(failure.toast).toBeNull();
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

describe("nothing outside this module shows a refusal's raw message", () => {
  /**
   * The rule #603 established and #655 finished applying: a refusal a BFF route
   * mints carries a `{ code }` and no sentence, and `getErrorMessage` is the
   * only reader that resolves one against the `errors` namespace. A site that
   * reads `.message` instead shows the code humanized into English - `Not
   * authenticated` - under every locale.
   *
   * Asserted by reading the source, because the failure is a *missing* call: a
   * test of the sites that were migrated cannot fail when a twenty-sixth is
   * added beside them.
   */
  const READS_MESSAGE = /instanceof (?:Api)?Error\s*\?\s*[A-Za-z_$][\w$]*\.message\b/;

  function sources(directory: string): string[] {
    const found: string[] = [];
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) found.push(...sources(path));
      else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) found.push(path);
    }
    return found;
  }

  it("reads it off a caught error nowhere the product renders", () => {
    const root = join(process.cwd(), "src");
    const offenders = ["app", "components", "hooks", "stores"]
      .flatMap((directory) => sources(join(root, directory)))
      .filter((path) => READS_MESSAGE.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(root.length + 1));

    expect(offenders).toEqual([]);
  });

  it("recognises the shapes that were really there", () => {
    // The two spellings the twenty-one migrated sites used, against the call
    // that replaced them.
    expect(READS_MESSAGE.test('e instanceof Error ? e.message : t("uploadFailed")')).toBe(true);
    expect(READS_MESSAGE.test('err instanceof ApiError ? err.message : t("saveFailed")')).toBe(
      true,
    );
    expect(READS_MESSAGE.test('getErrorMessage(e, tErrors, t("uploadFailed"))')).toBe(false);
    // And not the guard `use-auth` and friends do on a status, which reads no
    // message at all.
    expect(READS_MESSAGE.test("error instanceof ApiError && error.status === 401")).toBe(false);
  });
});
