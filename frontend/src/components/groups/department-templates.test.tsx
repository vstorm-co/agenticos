import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DepartmentTemplates } from "./department-templates";

const { mutateAsync } = vi.hoisted(() => ({ mutateAsync: vi.fn() }));
vi.mock("@/hooks", () => ({ useAddDepartments: () => ({ mutateAsync, isPending: false }) }));

const group = (name: string) => ({
  id: name,
  organization_id: "o-1",
  name,
  description: null,
  icon: null,
  member_count: 0,
  created_at: "2026-10-10T00:00:00Z",
});

describe("DepartmentTemplates", () => {
  it("offers the departments not yet there, the first five picked", async () => {
    mutateAsync.mockResolvedValue(4);
    const onClose = vi.fn();
    render(<DepartmentTemplates orgId="o-1" existing={[group("Sales")]} onClose={onClose} />);

    expect(screen.queryByText("Sales")).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: /Engineering/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add 4 departments" }));

    const sent = mutateAsync.mock.calls[0]![0] as { name: string; icon: string }[];
    expect(sent.map((department) => department.name)).toEqual([
      "Finance",
      "HR",
      "Support",
      "Marketing",
    ]);
    expect(sent[0]!.icon).toBe("banknote");
    expect(onClose).toHaveBeenCalled();
  });

  it("says when every department is already a group", () => {
    const names = [
      "Sales",
      "Finance",
      "HR",
      "Support",
      "Engineering",
      "Marketing",
      "Legal",
      "Operations",
    ];
    render(<DepartmentTemplates orgId="o-1" existing={names.map(group)} onClose={vi.fn()} />);

    expect(screen.getByText("Every department here is already a group.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add departments" })).toBeDisabled();
  });

  it("stays open when adding fails, which the hook has already said", async () => {
    mutateAsync.mockRejectedValue(new Error("refused"));
    const onClose = vi.fn();
    render(<DepartmentTemplates orgId="o-1" existing={[]} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: "Add 5 departments" }));

    expect(onClose).not.toHaveBeenCalled();
  });
});
