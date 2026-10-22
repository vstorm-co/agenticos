import { describe, expect, it } from "vitest";

import { IMPORT_COLUMNS, importTemplate } from "./import-columns";

describe("importTemplate", () => {
  it("writes every column the importer reads, and one case under them", async () => {
    const [header, example, ...rest] = (await importTemplate().text()).split("\r\n");

    expect(header).toBe(IMPORT_COLUMNS.join(","));
    expect(IMPORT_COLUMNS[0]).toBe("input");
    expect(example).toContain("How long does a refund take?");
    expect(example).toContain('"refunds,billing"');
    expect(example).toContain('"[{""type"": ""contains""');
    expect(rest).toEqual([""]);
  });
});
