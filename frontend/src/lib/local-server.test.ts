import { expect, it } from "vitest";
import { isLoopbackAddress } from "./local-server";
it.each(["http://localhost:3000", "http://127.0.0.1", "http://[::1]", "https://test.localhost"])(
  "recognizes links that only work on the current machine: %s",
  (url) => expect(isLoopbackAddress(url)).toBe(true),
);
it.each([
  "https://agents.example.com",
  "http://192.168.1.10",
  "invalid",
  "https://localhost.example.com",
])("does not invent a loopback restriction for %s", (url) =>
  expect(isLoopbackAddress(url)).toBe(false),
);
