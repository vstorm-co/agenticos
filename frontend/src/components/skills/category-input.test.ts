import { describe, expect, it } from "vitest";

import { categoryLabel, categorySuggestions } from "./category-input";

describe("categoryLabel", () => {
  it("turns a slug into a readable label", () => {
    // The stored value is a key two skills have to match on; the label is
    // what a person reads. Only the reading side changes.
    expect(categoryLabel("customer-support")).toBe("Customer support");
    expect(categoryLabel("engineering")).toBe("Engineering");
  });

  it("reads a word too short to be a word as an initialism", () => {
    expect(categoryLabel("hr")).toBe("HR");
    expect(categoryLabel("qa")).toBe("QA");
    expect(categoryLabel("ai-research")).toBe("AI research");
  });

  it("leaves a hand-written capitalized category alone", () => {
    // Somebody who typed "Legal" meant "Legal" - the helper only has to fix
    // slugs, not fight a choice.
    expect(categoryLabel("Legal")).toBe("Legal");
  });
});

describe("categorySuggestions", () => {
  it("lists the shelves in use before the predefined ones, without repeats", () => {
    expect(categorySuggestions(["devops", "legal"], ["marketing", "devops"])).toEqual([
      "devops",
      "legal",
      "marketing",
    ]);
  });
});
