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

  it("reads a semicolon file whose quoted header values hold more commas", () => {
    expect(parseCsv('"Last, first";"Total, EUR";Notes\nDoe;10,5;ok')).toEqual([
      ["Last, first", "Total, EUR", "Notes"],
      ["Doe", "10,5", "ok"],
    ]);
  });

  it("reads a comma file whose quoted header values hold more semicolons", () => {
    expect(parseCsv('"x;y;z",Total\n1,2')).toEqual([
      ["x;y;z", "Total"],
      ["1", "2"],
    ]);
  });

  it("reads escaped quotes that hold the other delimiter in a header", () => {
    expect(parseCsv('"a ""b;c;d""",Total\n1,2')).toEqual([
      ['a "b;c;d"', "Total"],
      ["1", "2"],
    ]);
  });

  it("reads a quoted header value that holds a line break", () => {
    expect(parseCsv('"a\nb";c\n1;2')).toEqual([
      ["a\nb", "c"],
      ["1", "2"],
    ]);
  });

  it("reads a quoted cell that is not the first cell of its row", () => {
    expect(parseCsv('a;"b;c"\n1;2')).toEqual([
      ["a", "b;c"],
      ["1", "2"],
    ]);
  });

  it("falls back to a comma when the header holds no separator to choose by", () => {
    expect(parseCsv("Name\nAcme;1")).toEqual([["Name"], ["Acme;1"]]);
  });

  it("reads a semicolon header whose second quoted name holds a comma", () => {
    expect(parseCsv('"Name";"Total, EUR"\nAcme;10,5')).toEqual([
      ["Name", "Total, EUR"],
      ["Acme", "10,5"],
    ]);
  });

  it("reads a comma header whose later quoted cell holds a semicolon", () => {
    expect(parseCsv('Name,"x;y;z"\n1,2')).toEqual([
      ["Name", "x;y;z"],
      ["1", "2"],
    ]);
  });

  it("reads a comma header whose later quoted cell holds escaped quotes and semicolons", () => {
    expect(parseCsv('Total,"a ""b;c;d"""\n1,2')).toEqual([
      ["Total", 'a "b;c;d"'],
      ["1", "2"],
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
