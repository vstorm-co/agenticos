/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import * as route from "./public/openapi.json/route";

describe("the public OpenAPI route", () => {
  it("is read-only: it mounts GET and nothing else", () => {
    expect(Object.keys(route)).toEqual(["GET"]);
    expect(route.GET).toEqual(expect.any(Function));
  });
});
