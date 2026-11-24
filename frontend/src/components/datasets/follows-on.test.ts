import { describe, expect, it } from "vitest";

import { asksAboutHistory, followsOn } from "./follows-on";

describe("followsOn", () => {
  it.each([
    "And how much to Toronto?",
    "What about Canada?",
    "how about next week?",
    "A co z wysyłką do Kanady?",
    "Und wie lange dauert das?",
    "Was ist mit Österreich?",
  ])("reads %o as continuing the conversation", (question) => {
    expect(followsOn(question)).toBe(true);
  });

  it.each([
    "How long do refunds take for a card payment?",
    "Do you offer gift wrapping on orders?",
    "Andorra is on my list, do you ship there?",
    "I need an invoice for order 12",
    "I bought shoes last week, can I return them?",
    "To whom should I send the receipt?",
    "Das ist kaputt, was nun?",
    "It arrived broken, what now?",
    "Do you ship?",
    "Refund policy?",
  ])("offers %o on its own", (question) => {
    expect(followsOn(question)).toBe(false);
  });
});

describe("asksAboutHistory", () => {
  it("asks unless nothing came before the question", () => {
    expect(asksAboutHistory(undefined)).toBe(true);
    expect(asksAboutHistory({ question: "And boots?", earlier: true })).toBe(true);
    expect(asksAboutHistory({ question: "And boots?", earlier: false })).toBe(false);
  });
});
