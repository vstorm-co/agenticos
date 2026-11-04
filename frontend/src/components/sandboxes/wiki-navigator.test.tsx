import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WikiNavigator } from "./wiki-navigator";
import { parseWikiPage } from "@/lib/wiki-graph";

it("uses the shared folder tree, keeps collapsed folders and opens attachments", async () => {
  const onSelect = vi.fn(),
    onFolder = vi.fn();
  const props = {
    files: ["notes/a.md", "notes/assets/photo.png", "report.pdf"].map((path) => ({
      path,
      size: 1,
      is_dir: false,
      modified_at: null,
    })),
    pages: [parseWikiPage("notes/a.md", "---\naliases: Discovery\n---\n# Alpha")],
    groups: ["notes"],
    grouping: "folder" as const,
    search: "",
    folder: null,
    selected: null,
    onSelect,
    onFolder,
  };
  const { rerender } = render(<WikiNavigator {...props} />);
  const user = userEvent.setup();
  expect(screen.getByRole("tree", { name: "Files" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Filter graph to notes" }));
  expect(onFolder).toHaveBeenCalledWith("notes");
  await user.click(screen.getByRole("button", { name: "assets" }));
  expect(screen.queryByRole("button", { name: "photo.png" })).not.toBeInTheDocument();
  rerender(<WikiNavigator {...props} files={[...props.files]} />);
  expect(screen.queryByRole("button", { name: "photo.png" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "report.pdf" }));
  expect(onSelect).toHaveBeenCalledWith("report.pdf");
  rerender(<WikiNavigator {...props} search="Discovery" folder="notes" />);
  expect(screen.getByRole("button", { name: "a.md" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "report.pdf" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear folder filter" }));
  expect(onFolder).toHaveBeenLastCalledWith(null);
});
