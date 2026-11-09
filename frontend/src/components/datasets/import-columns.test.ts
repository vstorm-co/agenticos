import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { IMPORT_COLUMNS, importTemplate, jsonlTemplate } from "./import-columns";

const here = resolve(__dirname);
const read = (path: string) => readFileSync(resolve(here, path), "utf-8");

describe("importTemplate", () => {
  it("writes a JSONL object accepted by the case editor, with structured checks and tags", async () => {
    const { caseContentFromJson } = await import("./case-form");
    const blob = jsonlTemplate();
    expect(blob.type).toBe("application/x-ndjson");
    const lines = (await blob.text()).trim().split("\n");
    expect(lines).toHaveLength(1);
    const line = lines[0];
    if (!line) throw new Error("The JSONL template has no case");
    const content = caseContentFromJson(JSON.parse(line));
    expect(content).toMatchObject({
      input: "How long does a refund take?",
      checks: [{ type: "contains", value: "5 working days" }],
      tags: ["refunds", "billing"],
    });
  });
  it("is the fixture the backend imports, quoting a cell with a comma or a quote", async () => {
    const template = await importTemplate().text();

    expect(template).toBe(read("import-template.fixture.csv"));
    expect(template.split("\n")[0]).toBe(IMPORT_COLUMNS.join(","));
    expect(template).toContain('"refunds,billing"');
    expect(template).toContain('"[{""type"": ""contains""');
  });

  it("names the importer's columns in its order", () => {
    const importer = read("../../../../backend/app/services/dataset_files.py");
    const columns = /^COLUMNS = \(([^)]*)\)/m.exec(importer)?.[1] ?? "";

    expect([...columns.matchAll(/"([^"]+)"/g)].map((match) => match[1])).toEqual([
      ...IMPORT_COLUMNS,
    ]);
  });
});
