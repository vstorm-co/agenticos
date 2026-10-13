import { describe, expect, it, vi } from "vitest";

import { separatorsFor } from "./number-parts";

describe("separatorsFor", () => {
  it("answers with English punctuation for English", () => {
    expect(separatorsFor("en")).toEqual({ separator: ",", decimalSeparator: "." });
  });

  it("answers with the locale's own punctuation, not English's", () => {
    // The whole reason this exists: `AnimatedCounter` draws one character per
    // cell rather than calling a formatter, so a hard-coded `,`/`.` pair would
    // print an English number inside a Polish page.
    expect(separatorsFor("de")).toEqual({ separator: ".", decimalSeparator: "," });
    expect(separatorsFor("pl").decimalSeparator).toBe(",");
  });

  it("falls back to English when nothing names a locale", () => {
    // `Intl` would answer with the runtime's own, which is the machine's
    // setting rather than the reader's - and a number whose grouping follows
    // the server it rendered on is worse than one that follows a default.
    const runtime = new Intl.NumberFormat().resolvedOptions().locale;
    expect(separatorsFor(undefined)).toEqual(separatorsFor(runtime));
  });

  it("falls back rather than throwing on a locale the runtime cannot read", () => {
    // A bad tag makes `Intl.NumberFormat` raise a RangeError, and a separator
    // is not worth a blank page: the figure still reads with the wrong comma,
    // where nothing reads at all with an exception.
    expect(separatorsFor("not a locale")).toEqual({ separator: ",", decimalSeparator: "." });
  });

  it("falls back when the formatter names no group or decimal part", () => {
    // Defensive, and cheap: `formatToParts` is a runtime's answer, not a
    // guarantee, and a missing part would otherwise put `undefined` into the
    // string a counter draws.
    vi.spyOn(Intl, "NumberFormat").mockImplementation(
      () => ({ formatToParts: () => [{ type: "integer", value: "1234" }] }) as never,
    );

    expect(separatorsFor("en")).toEqual({ separator: ",", decimalSeparator: "." });

    vi.restoreAllMocks();
  });
});
