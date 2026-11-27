import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ExportLayers } from "./export-layers";
import { OmissionNotice } from "./omission-notice";
import { ImportResourceChoice } from "./import-resource-choice";

it("keeps file layers explicit and makes unsupported content unavailable", async () => {
  const change = vi.fn();
  const props = {
    layers: ["definition", "skill_files", "context_content", "unsupported"],
    selected: ["definition"],
    format: "zip" as const,
    disabled: false,
    knowledgeBase: false,
    onChange: change,
  };
  const { rerender } = render(<ExportLayers {...props} />);
  expect(screen.getByRole("checkbox", { name: "Unavailable content layer" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Skill files" }));
  expect(change).toHaveBeenLastCalledWith(["definition", "skill_files"]);
  rerender(<ExportLayers {...props} selected={["definition", "skill_files", "context_content"]} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Skill files" }));
  expect(change).toHaveBeenLastCalledWith(["definition", "context_content"]);
  rerender(<ExportLayers {...props} layers={["definition"]} />);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});

it("keeps an omitted receipt understandable even when a restored result has no resource labels", async () => {
  render(
    <OmissionNotice
      resources={[]}
      omissions={{ "workflow/root": [["graph", "bindings", 0]] }}
      completed
    />,
  );
  await userEvent.click(screen.getByText("Show affected bindings"));
  expect(screen.getByText("workflow/root")).toBeVisible();
  expect(screen.getByText("graph › bindings › 0")).toBeVisible();
});

it("marks unsupported resource adapters as unresolved instead of offering a failing picker", async () => {
  render(
    <ImportResourceChoice
      resource={{
        key: "app/source",
        kind: "app",
        name: "App",
        source_id: null,
        source_parent_id: null,
        source_version: null,
        definition: null,
        references: [],
        included: [],
      }}
      choice={{ action: "skip" }}
      option={{ key: "app/source", available: false, can_create: false, reusable_id: null }}
      root={false}
      busy={false}
      parentId={undefined}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText(/This resource has no import adapter/)).toBeVisible();
  await userEvent.click(screen.getByRole("combobox", { name: "Action for App" }));
  expect(await screen.findByRole("option", { name: "Use an existing resource" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
