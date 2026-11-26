import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { BuildSection } from "./build-section";

it("retains a dirty editor when its native section is closed and reopened", async () => {
  render(
    <BuildSection title="Identity" defaultOpen>
      <input aria-label="Agent name" defaultValue="Assistant" />
    </BuildSection>,
  );
  const details = screen.getByLabelText("Agent name").closest("details");
  if (!details) throw new Error("Expected a native section");
  await userEvent.clear(screen.getByRole("textbox"));
  await userEvent.type(screen.getByRole("textbox"), "My assistant");
  act(() => {
    details.open = false;
    fireEvent(details, new Event("toggle"));
  });
  expect(details).not.toHaveAttribute("open");
  act(() => {
    details.open = true;
    fireEvent(details, new Event("toggle"));
  });
  expect(screen.getByRole("textbox")).toHaveValue("My assistant");
});

it("lets its parent reveal the model section", () => {
  const change = vi.fn();
  const view = render(
    <BuildSection title="Model" open={false} onOpenChange={change}>
      <input aria-label="Model id" />
    </BuildSection>,
  );
  expect(screen.getByLabelText("Model id").closest("details")).not.toHaveAttribute("open");
  view.rerender(
    <BuildSection title="Model" open onOpenChange={change}>
      <input aria-label="Model id" />
    </BuildSection>,
  );
  expect(screen.getByRole("textbox")).toBeVisible();
  const details = screen.getByLabelText("Model id").closest("details");
  if (!details) throw new Error("Expected a native section");
  act(() => {
    details.open = false;
    fireEvent(details, new Event("toggle"));
  });
  expect(change).toHaveBeenCalledWith(false);
});

it("opens when a late deep-link default arrives", () => {
  const view = render(
    <BuildSection title="Voice">
      <input aria-label="Voice model" />
    </BuildSection>,
  );
  view.rerender(
    <BuildSection title="Voice" defaultOpen>
      <input aria-label="Voice model" />
    </BuildSection>,
  );
  expect(screen.getByLabelText("Voice model").closest("details")).toHaveAttribute("open");
});

it("shows the current configuration while the editor is closed", () => {
  render(
    <BuildSection title="Model" summary="Sonnet · personal key">
      <input aria-label="Model name" />
    </BuildSection>,
  );
  expect(screen.getByText("Sonnet · personal key")).toBeVisible();
  expect(screen.getByLabelText("Model name").closest("details")).not.toHaveAttribute("open");
});

it("keeps primary model settings visible without a disclosure and retains draft edits", async () => {
  const view = render(
    <BuildSection
      title="Model"
      summary="Current model"
      framed={false}
      collapsible={false}
      description="The selected provider"
      headerEnd={<span>Help</span>}
    >
      <input aria-label="Model id" defaultValue="current" />
    </BuildSection>,
  );
  expect(screen.getByRole("heading", { name: "Model" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Model" })).toBeNull();
  expect(screen.getByLabelText("Model id").closest("details")).toBeNull();
  await userEvent.type(screen.getByRole("textbox"), "-draft");
  view.rerender(
    <BuildSection title="Model" summary="Current model" framed={false} collapsible={false}>
      <input aria-label="Model id" defaultValue="current" />
    </BuildSection>,
  );
  expect(screen.getByRole("textbox")).toHaveValue("current-draft");
});

it("keeps an optional inset row compact while retaining its configuration summary", () => {
  render(
    <BuildSection title="Variables" summary="2 custom variables" framed={false}>
      <input aria-label="Variable value" />
    </BuildSection>,
  );
  expect(screen.getByText("2 custom variables")).toBeVisible();
  expect(screen.getByLabelText("Variable value")).not.toBeVisible();
});
