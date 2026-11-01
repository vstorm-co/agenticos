/** @vitest-environment node */
import { expect, it } from "vitest";
import * as route from "./route";
it("exposes organization images through a read-only proxy route", () => {
  expect(Object.keys(route)).toEqual(["GET"]);
  expect(typeof route.GET).toBe("function");
});
