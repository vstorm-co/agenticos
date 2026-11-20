import { expect, it } from "vitest";
import { chatHomeVariant } from "./chat-home-variants";

it("offers ten distinct real chat previews by number or name", () => {
  const names = Array.from({ length: 10 }, (_, index) => chatHomeVariant(String(index + 1)));
  expect(new Set(names).size).toBe(10);
  expect(names[6]).toBe("timeline");
  for (const name of names) {
    expect(name).toBeDefined();
    expect(chatHomeVariant(name ?? null)).toBe(name);
  }
});

it("leaves the default chat unchanged without a supported variant", () => {
  expect(chatHomeVariant(null)).toBeUndefined();
  expect(chatHomeVariant("17")).toBeUndefined();
  expect(chatHomeVariant("7extra")).toBeUndefined();
});
