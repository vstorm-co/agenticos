import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DatasetVersion } from "@/types/datasets";
import { VersionSelect } from "./version-select";

const VERSIONS: DatasetVersion[] = [
  {
    id: "v2",
    number: 2,
    case_count: 101,
    change: "import",
    changed_cases: 100,
    created_by_user_id: null,
    created_at: "",
  },
  {
    id: "v1",
    number: 1,
    case_count: 1,
    change: "add",
    changed_cases: 1,
    created_by_user_id: null,
    created_at: "",
  },
];

describe("VersionSelect", () => {
  it("says what each version changed, and picks one or the newest", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <VersionSelect versions={VERSIONS} latest={2} value={null} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    expect(screen.getByRole("option", { name: "v2 · imported 100 cases" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "v1 · added 1 case" }));
    expect(onChange).toHaveBeenLastCalledWith(1);

    rerender(<VersionSelect versions={VERSIONS} latest={2} value={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: "Newest version" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("reaches a version older than the listed ones by its number", async () => {
    const onChange = vi.fn();
    const newest = VERSIONS.map((version) => ({ ...version, number: version.number + 300 }));
    const { rerender } = render(
      <VersionSelect versions={newest} latest={302} value={null} onChange={onChange} />,
    );
    const older = screen.getByRole("spinbutton", { name: "Older version #" });
    await userEvent.type(older, "7{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(7);
    await userEvent.type(older, "999{Enter}");
    await userEvent.type(older, "0");
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(older).toHaveValue(null);

    rerender(<VersionSelect versions={newest} latest={302} value={7} onChange={onChange} />);
    expect(screen.getByRole("combobox", { name: "Version" })).toHaveTextContent("v7");
  });

  it("offers no number box when the list already reaches version 1", () => {
    render(<VersionSelect versions={VERSIONS} latest={2} value={null} onChange={vi.fn()} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("offers no number box before any version exists", () => {
    render(<VersionSelect versions={[]} latest={0} value={null} onChange={vi.fn()} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });
});
