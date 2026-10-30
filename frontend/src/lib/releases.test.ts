import { expect, it } from "vitest";
import { isNewerRelease, parseVersion } from "./releases";

it.each([
  ["1.28.0", "1.29.0", true],
  ["1.9.0", "1.10.0", true],
  ["1.0.9", "1.0.10", true],
  ["1.28.0", "v1.28.0", false],
  ["1.29.0", "1.28.9", false],
  ["1.29.0-rc.1", "1.29.0", true],
  ["1.30.0-dev", "1.29.0", false],
  ["1.29.0+build.2", "1.29.0+build.3", false],
  ["1.29.0", "1.30.0-beta.1", false],
  ["development", "1.29.0", false],
  ["1.29.0", "latest", false],
])("compares %s to stable release %s", (current, latest, expected) => {
  expect(isNewerRelease(current, latest)).toBe(expected);
});
it.each([
  "1.2",
  "1.2.3.4",
  "01.2.3",
  "1.2.3-01",
  "1.2.3-beta..1",
  "1.2.3+build..1",
  "99999999999999999.1.1",
])("refuses invalid version %s", (value) => {
  expect(parseVersion(value)).toBeNull();
});
