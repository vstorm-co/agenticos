import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RuntimeField } from "./runtime-field";
import type { SandboxRuntime, SandboxRuntimeOption } from "@/lib/sandbox-connections-api";

function option(
  alias: string,
  overrides: Partial<SandboxRuntimeOption> = {},
): SandboxRuntimeOption {
  return {
    alias,
    description: `what ${alias} is for`,
    image: "python:3.12-slim",
    builds: false,
    ...overrides,
  };
}

function allowed(alias: string, overrides: Partial<SandboxRuntime> = {}): SandboxRuntime {
  return {
    alias,
    image: "python:3.12-slim",
    description: `what ${alias} is for`,
    builds: false,
    mem_limit: null,
    cpus: null,
    network_mode: null,
    ...overrides,
  };
}

function field(props: Partial<React.ComponentProps<typeof RuntimeField>> = {}) {
  const onChange = vi.fn();
  const onTest = vi.fn(async () => {});
  render(
    <RuntimeField
      value=""
      onChange={onChange}
      catalog={[option("coding", { builds: true }), option("node-minimal")]}
      allowed={null}
      onTest={onTest}
      testing={false}
      {...props}
    />,
  );
  return { onChange, onTest };
}

/**
 * Which image an agent gets by default.
 *
 * The list is the sandbox library's own catalog and is complete before anything is
 * probed - a select that only filled in after pressing a button was a select nobody
 * would find. Probing then answers the narrower question: this host may have been
 * started with a shorter allowlist, and the options it did not name are marked
 * rather than removed.
 */
describe("the default runtime", () => {
  it("offers the whole catalog with no host asked", async () => {
    field();

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    expect(await screen.findByRole("option", { name: /coding/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /node-minimal/ })).toBeVisible();
  });

  it("says plainly that no host has been checked yet", () => {
    // Offering fifteen aliases as though all fifteen will work is a promise this
    // cannot make until the service has answered.
    field();

    expect(
      screen.getByText(/Test the connection to see which ones this host allows/),
    ).toBeVisible();
  });

  it("marks what this host does not allow rather than dropping it", async () => {
    // Dropping it would leave somebody wondering where a runtime they have read
    // about went; marking it says which of the two things is wrong.
    field({ allowed: [allowed("coding")] });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    // Matched inside the option rather than through its accessible name: the
    // badge is `trailing`, and Radix names an item by its `ItemText` alone.
    const marked = await screen.findByRole("option", { name: /node-minimal/ });
    expect(within(marked).getByText("not on this host")).toBeVisible();
    expect(screen.getByText("This host allows 1 of them.")).toBeVisible();
  });

  it("keeps a runtime the host named that the library does not ship", async () => {
    // A runtime built for that deployment is exactly the case worth not dropping.
    field({ allowed: [allowed("in-house-cuda")] });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    expect(await screen.findByRole("option", { name: /in-house-cuda/ })).toBeVisible();
  });

  it("says which runtimes pay for a build on first use", async () => {
    field();

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    const builder = await screen.findByRole("option", { name: /coding/ });
    expect(within(builder).getByText("builds")).toBeVisible();
  });

  it("offers taking whatever the service defaults to", async () => {
    const { onChange } = field({ value: "coding" });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));
    await userEvent.click(screen.getByRole("option", { name: /Whatever the service defaults to/ }));

    expect(onChange).toHaveBeenCalledWith("");
  });

  it("keeps an alias nobody recognises rather than silently clearing it", async () => {
    // A stored value dropped while somebody edits an unrelated field is a
    // connection changing runtime with nobody deciding to.
    field({ value: "custom-image" });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    expect(screen.getByRole("option", { name: "custom-image" })).toBeVisible();
  });

  it("lets somebody type an alias built since this list was fetched", async () => {
    field();

    await userEvent.click(screen.getByRole("button", { name: "Type an alias instead" }));

    expect(screen.getByLabelText("Default runtime")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Pick from the list" }));
    expect(screen.getByRole("combobox", { name: "Default runtime" })).toBeVisible();
  });

  it("passes what was typed straight up", async () => {
    const { onChange } = field({ catalog: [] });

    await userEvent.type(screen.getByLabelText("Default runtime"), "p");

    expect(onChange).toHaveBeenCalledWith("p");
  });

  it("is a text field when the catalog could not be read at all", () => {
    // A failed catalog request must not leave the field unusable.
    field({ catalog: [] });

    expect(screen.getByLabelText("Default runtime")).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("asks the service when told to", async () => {
    const { onTest } = field();

    await userEvent.click(screen.getByRole("button", { name: "Test and check this host" }));

    expect(onTest).toHaveBeenCalled();
  });

  it("says it is asking, and cannot be asked twice at once", () => {
    field({ testing: true });

    expect(screen.getByRole("button", { name: /Asking the service/ })).toBeDisabled();
  });

  it("offers to ask again once it has an answer", () => {
    field({ allowed: [allowed("coding")] });

    expect(screen.getByRole("button", { name: "Ask again" })).toBeVisible();
  });

  it("offers no button when there is nothing to ask with", () => {
    field({ onTest: null });

    expect(screen.queryByRole("button", { name: /Test and check/ })).toBeNull();
  });

  it("keeps both badges in the list instead of repeating them on the trigger", async () => {
    // Radix draws the selected item's `ItemText` in the closed trigger, so a
    // badge in `children` was inherited by it: the field said "not on this
    // host" beside the very runtime the form was about to save, with nothing
    // left to compare it against. `trailing` renders outside `ItemText`.
    field({ value: "coding", allowed: [allowed("node-minimal")] });

    const trigger = screen.getByRole("combobox", { name: "Default runtime" });
    expect(trigger).toHaveTextContent("coding");
    expect(trigger).not.toHaveTextContent("builds");
    expect(trigger).not.toHaveTextContent("not on this host");

    await userEvent.click(trigger);

    // Both halves, because "absent from the trigger" alone is also true of a
    // component that stopped drawing them at all.
    const chosen = await screen.findByRole("option", { name: /coding/ });
    expect(within(chosen).getByText("builds")).toBeVisible();
    expect(within(chosen).getByText("not on this host")).toBeVisible();
  });

  it("keeps the runtime's own description on the trigger, which does describe it", async () => {
    // The line under the alias says what the image is for, which is true of the
    // option wherever it is drawn - so it stays in `children` and the trigger
    // is right to inherit it.
    field({ value: "coding" });

    expect(screen.getByRole("combobox", { name: "Default runtime" })).toHaveTextContent(
      "what coding is for",
    );
  });

  it("keeps the trigger inside its container, whatever the label says", () => {
    // An option label is a sentence, and a trigger that grew to fit one pushed the
    // dialog wider than the viewport.
    field({ value: "coding" });

    const trigger = screen.getByRole("combobox", { name: "Default runtime" });
    expect(trigger.className).toContain("min-w-0");
  });
});
