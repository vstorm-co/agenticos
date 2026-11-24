import { describe, expect, it } from "vitest";

import { similarFirst } from "./similar-first";

const cases = (...inputs: string[]) => inputs.map((input) => ({ input }));

describe("similarFirst", () => {
  it("puts the same question first, then rewordings, and keeps the order of the rest", () => {
    const ranked = similarFirst(
      cases("Do you ship to Canada?", "Refund window?", "", "What is the refund window?"),
      "What is the refund window?",
    );

    expect(ranked.map((item) => item.input)).toEqual([
      "What is the refund window?",
      "Refund window?",
      "Do you ship to Canada?",
      "",
    ]);
  });

  it("ranks nothing above anything for a question with no words", () => {
    const listed = cases("B?", "A?");
    expect(similarFirst(listed, " ?! ")).toEqual(listed);
  });
});
