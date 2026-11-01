import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeDefinition } from "@/components/workflows/validation/fixtures";
import type { NodeDefinition, NodeInstance, NodePolicy } from "@/lib/workflows/types";

import { PolicySection } from "./policy-section";

/**
 * A step's policy: whether its failures leave by an error port, how many tries it
 * gets and how long it waits between them, and its time limit. Retries are offered
 * only where repeating the call is safe, and an empty policy is no policy at all.
 */

const SAFE = makeDefinition({ id: "data.map", retry_guarantee: "idempotent" });
const UNSAFE = makeDefinition({ id: "agent.run", retry_guarantee: "none" });

function mount(policy: NodePolicy | null, definition: NodeDefinition = SAFE) {
  const updateNodePolicy = vi.fn();
  const node: NodeInstance = {
    id: "n",
    definition_id: definition.id,
    definition_version: 1,
    config: {},
    policy,
    layout: { x: 0, y: 0 },
  };
  render(<PolicySection definition={definition} node={node} updateNodePolicy={updateNodePolicy} />);
  return updateNodePolicy;
}

describe("PolicySection", () => {
  it("routes a step's failures to its error port, and back", async () => {
    const update = mount(null);
    await userEvent.click(screen.getByRole("switch", { name: "Handle errors" }));
    expect(update).toHaveBeenLastCalledWith("n", { on_error: "route" });
  });

  it("clears the policy when routing is turned off and nothing else is set", async () => {
    const update = mount({ on_error: "route" });
    await userEvent.click(screen.getByRole("switch", { name: "Handle errors" }));
    expect(update).toHaveBeenLastCalledWith("n", null);
  });

  it("sets how many tries a step gets, and back to the default", async () => {
    const update = mount(null);
    await userEvent.click(screen.getByRole("combobox", { name: "Tries" }));
    await userEvent.click(screen.getByRole("option", { name: "3 tries" }));
    expect(update).toHaveBeenLastCalledWith("n", { retry: { max_attempts: 3 } });
  });

  it("drops the retry schedule when the default is chosen again", async () => {
    const update = mount({ retry: { max_attempts: 3 } });
    await userEvent.click(screen.getByRole("combobox", { name: "Tries" }));
    await userEvent.click(screen.getByRole("option", { name: "Default" }));
    expect(update).toHaveBeenLastCalledWith("n", null);
  });

  it("chooses how the wait between tries grows, and the first wait", async () => {
    const update = mount({ retry: { max_attempts: 3, backoff: "exponential" } });
    await userEvent.click(screen.getByRole("combobox", { name: "Wait between tries" }));
    await userEvent.click(screen.getByRole("option", { name: "Fixed" }));
    expect(update).toHaveBeenLastCalledWith("n", {
      retry: { max_attempts: 3, backoff: "fixed" },
    });
    await userEvent.type(screen.getByLabelText("First wait (s)"), "5");
    expect(update).toHaveBeenLastCalledWith("n", {
      retry: { max_attempts: 3, backoff: "exponential", base_delay_seconds: 25 },
    });
  });

  it("ignores a first wait that is not a positive number", async () => {
    const update = mount({ retry: { max_attempts: 2 } });
    await userEvent.clear(screen.getByLabelText("First wait (s)"));
    expect(update).not.toHaveBeenCalled();
  });

  it("sets a time limit", () => {
    const update = mount(null);
    // A controlled field over a fixed prop: the whole value arrives at once.
    fireEvent.change(screen.getByLabelText("Time limit (s)"), { target: { value: "30" } });
    expect(update).toHaveBeenLastCalledWith("n", { timeout_seconds: 30 });
  });

  it("clears a time limit that is emptied", async () => {
    const update = mount({ timeout_seconds: 30 });
    await userEvent.clear(screen.getByLabelText("Time limit (s)"));
    expect(update).toHaveBeenLastCalledWith("n", null);
  });

  it("says why a step whose call is not safe to repeat is never retried", () => {
    mount(null, UNSAFE);
    expect(screen.getByRole("combobox", { name: "Tries" })).toBeDisabled();
    expect(screen.getByText(/not safe to repeat/)).toBeTruthy();
  });
});
