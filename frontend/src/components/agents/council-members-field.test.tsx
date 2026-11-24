import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CouncilMembersField } from "./council-members-field";

const state = vi.hoisted(() => ({
  profileId: "00000000-0000-4000-8000-000000000001",
}));

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: [{ id: state.profileId, provider: "anthropic" }],
    profilesStatus: "loaded",
  }),
}));

vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    onChange,
    disabled,
  }: {
    onChange: (profileId: string | null) => void;
    disabled?: boolean;
  }) => (
    <>
      <button
        type="button"
        aria-label="Choose model profile"
        disabled={disabled}
        onClick={() => onChange(state.profileId)}
      >
        Choose model profile
      </button>
      <button type="button" disabled={disabled} onClick={() => onChange(null)}>
        Clear model profile
      </button>
    </>
  ),
}));

describe("CouncilMembersField", () => {
  it("renders exactly three fixed member rows", () => {
    render(<CouncilMembersField idPrefix="council" value={undefined} onChange={vi.fn()} />);

    expect(screen.getAllByRole("group", { name: /Member [123]/ })).toHaveLength(3);
    expect(screen.getAllByLabelText("Name")).toHaveLength(3);
    expect(screen.getAllByLabelText("Provider")).toHaveLength(3);
  });

  it("emits all three schema-shaped members when a name changes", () => {
    const onChange = vi.fn();
    render(<CouncilMembersField idPrefix="council" value={undefined} onChange={onChange} />);

    const firstMember = screen.getByRole("group", { name: "Member 1" });
    fireEvent.change(within(firstMember).getByLabelText("Name"), {
      target: { value: "Reviewer A" },
    });

    expect(onChange).toHaveBeenCalledWith([
      { name: "Reviewer A", provider: "", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
    ]);
  });

  it("stores the chosen profile id and its provider", async () => {
    const onChange = vi.fn();
    render(<CouncilMembersField idPrefix="council" value={undefined} onChange={onChange} />);

    const firstMember = screen.getByRole("group", { name: "Member 1" });
    await userEvent.click(
      within(firstMember).getByRole("button", { name: "Choose model profile" }),
    );

    expect(onChange).toHaveBeenCalledWith([
      { name: "", provider: "anthropic", model_profile_id: state.profileId },
      { name: "", provider: "", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
    ]);
  });

  it("disables every member control when editing is disabled", () => {
    render(
      <CouncilMembersField idPrefix="council" value={undefined} onChange={vi.fn()} disabled />,
    );

    screen.getAllByLabelText("Name").forEach((input) => expect(input).toBeDisabled());
    screen.getAllByLabelText("Provider").forEach((input) => expect(input).toBeDisabled());
    screen
      .getAllByRole("button", { name: "Choose model profile" })
      .forEach((button) => expect(button).toBeDisabled());
  });

  it("preserves valid stored members and normalizes malformed entries before editing a provider", () => {
    const onChange = vi.fn();
    const first = { name: "Reviewer A", provider: "custom", model_profile_id: "saved-profile" };
    render(
      <CouncilMembersField
        idPrefix="council"
        value={[first, { name: 12, provider: false, model_profile_id: null }, null]}
        onChange={onChange}
      />,
    );

    const firstMember = screen.getByRole("group", { name: "Member 1" });
    const secondMember = screen.getByRole("group", { name: "Member 2" });
    const thirdMember = screen.getByRole("group", { name: "Member 3" });
    expect(within(firstMember).getByLabelText("Name")).toHaveValue("Reviewer A");
    expect(within(firstMember).getByLabelText("Provider")).toHaveValue("custom");
    expect(within(secondMember).getByLabelText("Name")).toHaveValue("");
    expect(within(thirdMember).getByLabelText("Provider")).toHaveValue("");
    fireEvent.change(within(secondMember).getByLabelText("Provider"), {
      target: { value: "reviewer-provider" },
    });

    expect(onChange).toHaveBeenCalledWith([
      first,
      { name: "", provider: "reviewer-provider", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
    ]);
  });

  it("clears a saved model without silently replacing the member's provider", async () => {
    const onChange = vi.fn();
    render(
      <CouncilMembersField
        idPrefix="council"
        value={[{ name: "Reviewer A", provider: "custom", model_profile_id: state.profileId }]}
        onChange={onChange}
      />,
    );
    await userEvent.click(
      within(screen.getByRole("group", { name: "Member 1" })).getByRole("button", {
        name: "Clear model profile",
      }),
    );
    expect(onChange).toHaveBeenCalledWith([
      { name: "Reviewer A", provider: "custom", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
      { name: "", provider: "", model_profile_id: "" },
    ]);
  });
});
