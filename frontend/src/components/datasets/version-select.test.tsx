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
      <VersionSelect versions={VERSIONS} value={null} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    expect(screen.getByRole("option", { name: "v2 · imported 100 cases" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "v1 · added 1 case" }));
    expect(onChange).toHaveBeenLastCalledWith(1);

    rerender(<VersionSelect versions={VERSIONS} value={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: "Newest version" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
