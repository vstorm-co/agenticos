import { expect, it } from "vitest";
import { directionFor } from "./navigation-direction";

it("keeps a back transition stable on rerender and resets the next push", () => {
  expect(directionFor("/first")).toBe("forward");
  window.dispatchEvent(new PopStateEvent("popstate"));
  expect(directionFor("/previous")).toBe("back");
  expect(directionFor("/previous")).toBe("back");
  expect(directionFor("/next")).toBe("forward");
});
