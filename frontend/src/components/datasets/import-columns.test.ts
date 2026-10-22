import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { IMPORT_COLUMNS, importTemplate } from "./import-columns";

const here = resolve(__dirname);
const read = (path: string) => readFileSync(resolve(here, path), "utf-8");

describe("importTemplate", () => {
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
