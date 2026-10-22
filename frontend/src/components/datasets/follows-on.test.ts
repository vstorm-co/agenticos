import { describe, expect, it } from "vitest";

import { followsOn } from "./follows-on";

describe("followsOn", () => {
  it.each([
    "And how much to Toronto?",
    "What about Canada?",
    "it's broken again, what now?",
    "A co z wysyłką do Kanady?",
    "Und wie lange dauert das?",
    "Toronto?",
    "  why not  ",
  ])("reads %o as continuing the conversation", (question) => {
    expect(followsOn(question)).toBe(true);
  });

  it.each([
    "How long do refunds take for a card payment?",
    "Do you offer gift wrapping on orders?",
    "Items bought in the sale, can they be returned?",
    "Andorra is on my list, do you ship there?",
  ])("reads %o as a question of its own", (question) => {
    expect(followsOn(question)).toBe(false);
  });
});
