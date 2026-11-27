import { describe, expect, it } from "vitest";

import { parseEnvironmentEvent } from "./environment-stream";

const expected = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: "11111111-1111-4111-8111-111111111111",
  kind: "browser" as const,
  execution_target: "agent" as const,
};
const state = {
  ...expected,
  state: "ready",
  control: "agent",
  can_control: true,
  expires_at: null,
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};
const frame = {
  kind: "browser_frame",
  call_id: expected.id,
  step: 1,
  image: "data:image/jpeg;base64,AA==",
};

describe("environment stream boundary", () => {
  it("accepts a state for this exact environment", () => {
    const event = { type: "environment_state", data: state };
    expect(parseEnvironmentEvent(event, expected)).toEqual(event);
  });
  it("accepts the existing browser event with a stable environment identity", () => {
    const event = { type: "browser_event", data: frame };
    expect(parseEnvironmentEvent(event, expected)).toEqual(event);
  });
  it.each([
    { type: "environment_state", data: { ...state, id: "44444444-4444-4444-8444-444444444444" } },
    {
      type: "environment_state",
      data: { ...state, agent_id: "44444444-4444-4444-8444-444444444444" },
    },
    { type: "environment_state", data: { ...state, kind: "desktop" } },
    { type: "environment_state", data: { ...state, can_control: "true" } },
    { type: "browser_event", data: { ...frame, call_id: "old-tool-call" } },
    { type: "browser_event", data: { ...frame, step: -1 } },
    { type: "browser_event", data: { ...frame, image: "https://other.example/image" } },
    { type: "browser_event", data: { ...frame, image: "data:image/svg+xml,<svg/>" } },
    { type: "browser_event", data: { ...frame, x: Number.NaN } },
    { type: "unknown", data: state },
    null,
  ])("refuses malformed or differently scoped data", (event) => {
    expect(parseEnvironmentEvent(event, expected)).toBeNull();
  });
  it("accepts an actual desktop screenshot without inventing a run", () => {
    const data = { ...frame, navigable: false, run_id: null, image: "data:image/png;base64,AA==" };
    expect(
      parseEnvironmentEvent({ type: "browser_event", data }, { ...expected, kind: "desktop" }),
    ).toEqual({ type: "browser_event", data });
  });
});
