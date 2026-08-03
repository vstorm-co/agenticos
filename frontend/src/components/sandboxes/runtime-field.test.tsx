import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RuntimeField } from "./runtime-field";
import type { SandboxRuntime } from "@/lib/sandbox-connections-api";

function runtime(alias: string, description = ""): SandboxRuntime {
  return {
    alias,
    image: `ghcr.io/example/${alias}`,
    description,
    builds: false,
    mem_limit: null,
    cpus: null,
    network_mode: null,
  };
}

function field(props: Partial<React.ComponentProps<typeof RuntimeField>> = {}) {
  const onChange = vi.fn();
  const onTest = vi.fn(async () => {});
  render(
    <RuntimeField
      value=""
      onChange={onChange}
      runtimes={null}
      onTest={onTest}
      testing={false}
      {...props}
    />,
  );
  return { onChange, onTest };
}

/**
 * Which image an agent gets by default, and why it stopped being free text.
 *
 * An alias is the service's own configuration, so a typo cannot be caught here -
 * only by asking. Before anybody has asked, this is a text field; afterwards it is
 * the list the service gave, with the text field still reachable because that list
 * is a snapshot of a service somebody may have just reconfigured.
 */
describe("the default runtime", () => {
  it("is a text field before anybody has asked the service", () => {
    field();

    expect(screen.getByLabelText("Default runtime")).toHaveValue("");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("becomes a list of what the service named", async () => {
    field({ runtimes: [runtime("python", "Python 3.12"), runtime("node")] });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    expect(await screen.findByRole("option", { name: /python — Python 3.12/ })).toBeVisible();
    expect(screen.getByRole("option", { name: "node" })).toBeVisible();
  });

  it("offers taking whatever the service defaults to", async () => {
    const { onChange } = field({ value: "python", runtimes: [runtime("python")] });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));
    await userEvent.click(screen.getByRole("option", { name: /Whatever the service defaults to/ }));

    expect(onChange).toHaveBeenCalledWith("");
  });

  it("keeps an alias the service did not name rather than silently clearing it", async () => {
    // A stored value dropped while somebody edits an unrelated field is a
    // connection changing runtime with nobody deciding to.
    field({ value: "custom-image", runtimes: [runtime("python")] });

    await userEvent.click(screen.getByRole("combobox", { name: "Default runtime" }));

    expect(screen.getByRole("option", { name: "custom-image" })).toBeVisible();
  });

  it("lets somebody type an alias the list does not have yet", async () => {
    // An operator who has just added one to the service's configuration and not
    // restarted it is describing something true this cannot see.
    field({ runtimes: [runtime("python")] });

    await userEvent.click(screen.getByRole("button", { name: "Type an alias instead" }));

    expect(screen.getByLabelText("Default runtime")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Pick from the list" }));
    expect(screen.getByRole("combobox", { name: "Default runtime" })).toBeVisible();
  });

  it("passes what was typed straight up", async () => {
    const { onChange } = field();

    await userEvent.type(screen.getByLabelText("Default runtime"), "p");

    expect(onChange).toHaveBeenCalledWith("p");
  });

  it("asks the service when told to", async () => {
    const { onTest } = field();

    await userEvent.click(screen.getByRole("button", { name: "Test and list runtimes" }));

    expect(onTest).toHaveBeenCalled();
  });

  it("says it is asking, and cannot be asked twice at once", () => {
    field({ testing: true });

    expect(screen.getByRole("button", { name: /Asking the service/ })).toBeDisabled();
  });

  it("offers to ask again once it has an answer", () => {
    field({ runtimes: [runtime("python")] });

    expect(screen.getByRole("button", { name: "Ask again" })).toBeVisible();
  });

  it("offers no button when there is nothing to ask with", () => {
    field({ onTest: null });

    expect(screen.queryByRole("button", { name: /Test and list/ })).toBeNull();
  });

  it("stays a text field when the service allows nothing at all", () => {
    // "No runtimes" is a real answer and a real problem, and an empty list is not
    // a list worth switching a form over to.
    field({ runtimes: [] });

    expect(screen.getByLabelText("Default runtime")).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
