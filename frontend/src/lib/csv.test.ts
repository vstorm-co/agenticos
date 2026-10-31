import { describe, expect, it } from "vitest";

import { parseCsv } from "./csv";

describe("parseCsv", () => {
  it("reads rows and cells, dropping a byte-order mark and the final line break", () => {
    expect(parseCsv("﻿Name,Seats\r\nAcme,3\r\n")).toEqual([
      ["Name", "Seats"],
      ["Acme", "3"],
    ]);
  });

  it("keeps a quoted cell's delimiter, line break and doubled quote", () => {
    expect(parseCsv('a,b\n"one, two","say ""hi""\nthere"\n')).toEqual([
      ["a", "b"],
      ["one, two", 'say "hi"\nthere'],
    ]);
  });

  it("splits on semicolons when the header holds more of them", () => {
    expect(parseCsv("Name;Total\nAcme;10,5")).toEqual([
      ["Name", "Total"],
      ["Acme", "10,5"],
    ]);
  });

  it("keeps an empty last cell and reads a quote inside a cell as text", () => {
    expect(parseCsv('a,b\n1,\n2,x"y')).toEqual([
      ["a", "b"],
      ["1", ""],
      ["2", 'x"y'],
    ]);
  });

  it("reads nothing from an empty file", () => {
    expect(parseCsv("")).toEqual([]);
  });
});
