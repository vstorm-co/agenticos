import { describe, expect, it } from "vitest";

import {
  buildReference,
  curlExample,
  fieldsOf,
  humanizeTag,
  matchesQuery,
  typeLabel,
  type OpenApiDocument,
  type ReferenceOperation,
} from "./reference";

const DOCUMENT: OpenApiDocument = {
  info: { title: "public", version: "1.2.3" },
  paths: {
    "/api/v1/agents/{agent_id}/run": {
      post: {
        tags: ["agents"],
        summary: "Run Agent",
        description: "Run a published agent.",
        operationId: "run_agent",
        parameters: [
          {
            name: "agent_id",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
          { name: "x-organization-id", in: "header", schema: { type: "string" } },
          { name: "dry_run", in: "query", schema: { type: "boolean" } },
        ],
        requestBody: {
          content: { "application/json": { schema: { $ref: "#/components/schemas/RunRequest" } } },
        },
        responses: { "200": { description: "The answer" }, "429": {} },
      },
    },
    "/api/v1/agents": { get: { tags: ["agents"], summary: "List Agents" } },
    "/api/v1/ml/services": { get: { tags: ["ml-services"] } },
    "/api/v1/untagged": { delete: {} },
  },
  components: {
    schemas: {
      RunRequest: {
        type: "object",
        required: ["prompt", "count", "flag", "ids"],
        properties: {
          prompt: { type: "string", description: "What to ask" },
          count: { type: "integer" },
          flag: { type: "boolean", title: "A flag" },
          ids: { type: "array", items: { type: "string", format: "uuid" } },
          extra: { anyOf: [{ $ref: "#/components/schemas/Extra" }, { type: "null" }] },
        },
      },
    },
  },
};

/** One operation of the sample document, by group and position - failing loudly when absent. */
function operation(groupIndex: number, index: number): ReferenceOperation {
  const found = buildReference(DOCUMENT)[groupIndex]?.operations[index];
  if (!found) throw new Error(`no operation ${groupIndex}/${index}`);
  return found;
}

describe("buildReference", () => {
  it("groups operations by their first tag, in the order the document names them", () => {
    const groups = buildReference(DOCUMENT);
    expect(groups.map((group) => group.tag)).toEqual(["agents", "ml-services", "other"]);
    expect(groups[0]?.operations.map((op) => `${op.method} ${op.path}`)).toEqual([
      "post /api/v1/agents/{agent_id}/run",
      "get /api/v1/agents",
    ]);
  });

  it("reads parameters without the organization header, the body's fields and the responses", () => {
    const run = operation(0, 0);
    expect(run.id).toBe("run_agent");
    expect(run.parameters).toEqual([
      {
        name: "agent_id",
        location: "path",
        required: true,
        type: "string (uuid)",
        description: null,
      },
      { name: "dry_run", location: "query", required: false, type: "boolean", description: null },
    ]);
    expect(run.bodyType).toBe("RunRequest");
    expect(
      run.body.map((field) => [field.name, field.required, field.type, field.description]),
    ).toEqual([
      ["prompt", true, "string", "What to ask"],
      ["count", true, "integer", null],
      ["flag", true, "boolean", "A flag"],
      ["ids", true, "string (uuid)[]", null],
      ["extra", false, "Extra | null", null],
    ]);
    expect(run.responses).toEqual([
      { status: "200", description: "The answer" },
      { status: "429", description: "" },
    ]);
  });

  it("falls back for an operation with no summary, id, tags or body", () => {
    const untagged = operation(2, 0);
    expect(untagged).toMatchObject({
      id: "delete-/api/v1/untagged",
      summary: "/api/v1/untagged",
      description: null,
      bodyType: null,
      body: [],
      parameters: [],
      responses: [],
    });
  });

  it("reads a document without components", () => {
    expect(buildReference({ info: DOCUMENT.info, paths: {} })).toEqual([]);
  });
});

describe("typeLabel", () => {
  it.each([
    [undefined, "any"],
    [{}, "any"],
    [{ type: "null" }, "null"],
    [{ enum: ["a", 1] }, '"a" | 1'],
    [{ allOf: [{ $ref: "#/components/schemas/Agent" }] }, "Agent"],
    [{ oneOf: [{ type: "string" }, { type: "integer" }] }, "string | integer"],
    [{ type: "array" }, "any[]"],
  ])("labels %j as %s", (schema, label) => {
    expect(typeLabel(schema)).toBe(label);
  });
});

describe("fieldsOf", () => {
  it("is empty for a schema with no properties or one it cannot resolve", () => {
    expect(fieldsOf({ type: "string" }, {})).toEqual([]);
    expect(fieldsOf({ $ref: "#/components/schemas/Missing" }, {})).toEqual([]);
    expect(fieldsOf({ properties: { a: {} } }, {})).toEqual([
      { name: "a", location: null, required: false, type: "any", description: null },
    ]);
  });
});

describe("humanizeTag", () => {
  it("reads a tag as a heading and keeps the acronyms", () => {
    expect(humanizeTag("knowledge-bases")).toBe("Knowledge bases");
    expect(humanizeTag("ml-services")).toBe("ML services");
    expect(humanizeTag("rag")).toBe("RAG");
  });
});

describe("matchesQuery", () => {
  const run = operation(0, 0);

  it("matches the path, summary, group or method, ignoring case and blanks", () => {
    expect(matchesQuery(run, "")).toBe(true);
    expect(matchesQuery(run, "  RUN  ")).toBe(true);
    expect(matchesQuery(run, "agents")).toBe(true);
    expect(matchesQuery(run, "post")).toBe(true);
    expect(matchesQuery(run, "invitations")).toBe(false);
  });
});

describe("curlExample", () => {
  it("calls the operation with a body of its required fields", () => {
    const run = operation(0, 0);
    const list = operation(0, 1);
    expect(curlExample(run, "https://os.example.com")).toBe(
      [
        'curl -X POST "https://os.example.com/api/v1/agents/{agent_id}/run"',
        '  -H "Authorization: Bearer $AGENTICOS_API_KEY"',
        '  -H "Content-Type: application/json"',
        `  -d '{"prompt": "…", "count": 0, "flag": false, "ids": []}'`,
      ].join(" \\\n"),
    );
    expect(curlExample(list, "")).not.toContain("Content-Type");
  });

  it("writes an empty object for a field of another type", () => {
    const op = { ...operation(0, 0) };
    op.body = [{ name: "meta", location: null, required: true, type: "Meta", description: null }];
    expect(curlExample(op, "")).toContain(`'{"meta": {}}'`);
  });
});
