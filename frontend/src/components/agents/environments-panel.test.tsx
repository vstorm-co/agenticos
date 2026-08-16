import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EnvironmentsPanel } from "./environments-panel";
import { VERSION_HISTORY_LIMIT } from "@/lib/agent-spec";

type Environment = {
  id: string;
  name: string;
  version_id: string;
  version: number;
  is_default: boolean;
};

const state = {
  environments: [] as Environment[],
  isLoading: false,
  create: { mutateAsync: vi.fn(), isPending: false },
  promote: { mutate: vi.fn(), isPending: false },
  rename: { mutateAsync: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
};

const versionsState = {
  versions: [] as { id: string; version: number }[],
  isLoading: false,
};

vi.mock("@/hooks", () => ({
  useAgentEnvironments: () => state,
  useAgentVersions: () => versionsState,
}));

function environment(name: string, version: number, is_default = false): Environment {
  return { id: `${name}-id`, name, version_id: `v${version}-id`, version, is_default };
}

beforeEach(() => {
  state.environments = [environment("production", 3, true), environment("staging", 2)];
  state.isLoading = false;
  state.create = { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
  state.promote = { mutate: vi.fn(), isPending: false };
  state.rename = { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
  state.remove = { mutate: vi.fn(), isPending: false };
  versionsState.versions = [
    { id: "v3-id", version: 3 },
    { id: "v2-id", version: 2 },
    { id: "v1-id", version: 1 },
  ];
});

describe("the environments panel", () => {
  it("says nothing at all while the environments are loading", () => {
    // A panel that flashes an empty state and then fills in reads as a bug.
    state.isLoading = true;
    const { container } = render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing for an agent that was never published", () => {
    // The first publish mints `production`; before that there is nothing to
    // manage and no name to pin.
    state.environments = [];
    const { container } = render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says which version each name serves", () => {
    // The whole point of an environment: a bot bound to it serves that version,
    // and which one is the question somebody opens this panel to answer.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByText(/serves v3/)).toBeInTheDocument();
    expect(screen.getByText(/serves v2/)).toBeInTheDocument();
  });

  it("marks the default, and says what being the default means", () => {
    // Publish moves only this one. Somebody who does not know that publishes and
    // wonders why staging did not change.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText(/what publish repoints/)).toBeInTheDocument();
  });

  it("refuses to offer removal of the default", () => {
    // Removing it would leave publish with nothing to move.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.queryByRole("button", { name: "Remove production" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove staging" })).toBeInTheDocument();
  });

  it("removes the environment it names", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove staging" }));

    expect(state.remove.mutate).toHaveBeenCalledWith("staging-id");
  });

  it("shows nothing to manage to somebody who may not manage it", () => {
    render(<EnvironmentsPanel agentId="a1" canManage={false} />);

    expect(screen.getByText(/serves v3/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove staging" })).toBeNull();
    expect(screen.queryByLabelText("New environment")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Rename staging" })).toBeNull();
  });

  it("pins another version from the environment's own row", async () => {
    // "dev should serve v3" is answered on the row that states what dev
    // serves, not by scanning the version list for v3.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("combobox", { name: "Pin a version for staging" }));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));

    expect(state.promote.mutate).toHaveBeenCalledWith({
      environmentId: "staging-id",
      versionId: "v1-id",
    });
  });

  it("does not promote onto the version already served", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("combobox", { name: "Pin a version for staging" }));
    await userEvent.click(screen.getByRole("option", { name: "v2" }));

    expect(state.promote.mutate).not.toHaveBeenCalled();
  });

  it("stops a second promotion while one is in flight", () => {
    state.promote = { mutate: vi.fn(), isPending: true };
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByRole("combobox", { name: "Pin a version for staging" })).toBeDisabled();
  });

  it("names a pinned version that no longer exists instead of going blank", () => {
    // An environment pinned at a deleted version is why the agent is not
    // answering; an empty select would hide exactly that.
    state.environments = [
      environment("production", 3, true),
      { id: "dev-id", name: "dev", version_id: "gone-id", version: 9, is_default: false },
    ];
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByRole("combobox", { name: "Pin a version for dev" })).toHaveTextContent(
      "v9 (removed)",
    );
  });

  it("does not call a pin removed while the history is unread", () => {
    // The environments query and the versions query race; an empty history is
    // a request in flight, and reading it as "removed" would flash the worst
    // verdict this panel has onto every row on every load - the reading
    // `pinStatus` already refused.
    state.environments = [
      { id: "dev-id", name: "dev", version_id: "v9-id", version: 9, is_default: false },
    ];
    versionsState.versions = [];
    render(<EnvironmentsPanel agentId="a1" canManage />);

    const trigger = screen.getByRole("combobox", { name: "Pin a version for dev" });
    expect(trigger).toHaveTextContent("v9");
    expect(trigger).not.toHaveTextContent("removed");
  });

  it("does not call a pin removed when the history may be truncated", () => {
    // The backend caps the history at fifty; a pin older than fifty publishes
    // is off the end of the page, which is not the same fact as deleted.
    state.environments = [
      { id: "dev-id", name: "dev", version_id: "v9-id", version: 9, is_default: false },
    ];
    versionsState.versions = Array.from({ length: VERSION_HISTORY_LIMIT }, (_, index) => ({
      id: `v${index + 10}-id`,
      version: index + 10,
    }));
    render(<EnvironmentsPanel agentId="a1" canManage />);

    const trigger = screen.getByRole("combobox", { name: "Pin a version for dev" });
    expect(trigger).toHaveTextContent("v9");
    expect(trigger).not.toHaveTextContent("removed");
  });

  it("renames an environment from its own row", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    const field = screen.getByRole("textbox", { name: "Rename staging" });
    await userEvent.clear(field);
    await userEvent.type(field, "canary");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(state.rename.mutateAsync).toHaveBeenCalledWith({
      environmentId: "staging-id",
      name: "canary",
    });
  });

  it("submits a rename on Enter and trims it first", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    const field = screen.getByRole("textbox", { name: "Rename staging" });
    await userEvent.clear(field);
    await userEvent.type(field, "canary {enter}");

    expect(state.rename.mutateAsync).toHaveBeenCalledWith({
      environmentId: "staging-id",
      name: "canary",
    });
  });

  it("abandons a rename on Escape and on Cancel, sending nothing", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Rename staging" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("textbox", { name: "Rename staging" })).toBeNull();
    expect(state.rename.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("staging")).toBeInTheDocument();
  });

  it("closes a rename that changed nothing without sending it", async () => {
    // Enter on the untouched name is a dismissal; sending it would write the
    // row and mint an audit entry for a rename nobody made.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Rename staging" }), "{enter}");

    expect(screen.queryByRole("textbox", { name: "Rename staging" })).toBeNull();
    expect(state.rename.mutateAsync).not.toHaveBeenCalled();
  });

  it("refuses a rename the backend's slug rule would reject", async () => {
    // Checked before the request leaves, exactly like creation - the refusal
    // would otherwise arrive as a 422 about a pattern nobody was shown.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Rename staging" }));
    const field = screen.getByRole("textbox", { name: "Rename staging" });
    await userEvent.clear(field);
    await userEvent.type(field, "Staging Two{enter}");

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(state.rename.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not offer to rename the default", () => {
    // Its name is part of the publish contract; the backend refuses the
    // rename, so the button must not exist.
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.queryByRole("button", { name: "Rename production" })).toBeNull();
  });

  it("refuses a name the backend's slug rule would reject", async () => {
    // Checked before the request leaves, because the refusal would otherwise
    // arrive as a 422 about a pattern nobody was shown.
    render(<EnvironmentsPanel agentId="a1" canManage />);
    const add = screen.getByRole("button", { name: "Add" });

    await userEvent.type(screen.getByLabelText("New environment"), "Staging Two");

    expect(add).toBeDisabled();
  });

  it("refuses a name that starts with a hyphen", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.type(screen.getByLabelText("New environment"), "-dev");

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("accepts an ordinary slug and clears the field afterwards", async () => {
    // Leaving the name behind invites a second identical environment, which the
    // backend then refuses.
    render(<EnvironmentsPanel agentId="a1" canManage />);
    const field = screen.getByLabelText("New environment");

    await userEvent.type(field, "dev");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({ name: "dev" });
    expect(field).toHaveValue("");
  });

  it("trims before it validates and before it sends", async () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    await userEvent.type(screen.getByLabelText("New environment"), "  dev  ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({ name: "dev" });
  });

  it("cannot be submitted empty", () => {
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("stops a second submission while one is in flight", () => {
    state.create = { mutateAsync: vi.fn(), isPending: true };
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("stops a second removal while one is in flight", () => {
    state.remove = { mutate: vi.fn(), isPending: true };
    render(<EnvironmentsPanel agentId="a1" canManage />);

    expect(screen.getByRole("button", { name: "Remove staging" })).toBeDisabled();
  });
});
