import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DEFAULT_ENV, EnvironmentField } from "./environment-field";
import type { AgentEnvironment } from "@/types/agents";

function env(overrides: Partial<AgentEnvironment>): AgentEnvironment {
  return {
    id: "e1",
    agent_id: "a1",
    name: "staging",
    version_id: "v1",
    version: 3,
    is_default: false,
    tracks_latest: false,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

/** Controlled, so picking an option actually moves the caption. */
function Harness({
  environments,
  defaultEnvironment = null,
}: {
  environments: AgentEnvironment[];
  defaultEnvironment?: AgentEnvironment | null;
}) {
  const [value, setValue] = useState(DEFAULT_ENV);
  return (
    <EnvironmentField
      value={value}
      onChange={setValue}
      environments={environments}
      defaultEnvironment={defaultEnvironment}
    />
  );
}

/**
 * A trigger fires with nobody watching, so the environment picker is the only
 * moment anyone reads what a fire will actually run. Each row must say more
 * than a name: the version, whether it follows publishes, and how far a pinned
 * one is behind - and the caption must say what the next fire runs.
 */
describe("EnvironmentField", () => {
  it("marks a tracking environment and says a pinned one is behind", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        environments={[
          env({ id: "e1", name: "prod", version: 7, tracks_latest: true }),
          env({ id: "e2", name: "staging", version: 3, behind_by: 4 }),
        ]}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Environment" }));
    const prod = await screen.findByRole("option", { name: /prod/ });
    expect(prod).toHaveTextContent("v7");
    expect(prod).toHaveTextContent("follows publishes");
    const staging = screen.getByRole("option", { name: /staging/ });
    expect(staging).toHaveTextContent("v3");
    expect(staging).toHaveTextContent("4 versions behind");
  });

  it("captions what the next fire will run, for each kind of binding", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        environments={[
          env({ id: "e1", name: "prod", version: 7, tracks_latest: true }),
          env({ id: "e2", name: "staging", version: 3, behind_by: 4 }),
        ]}
      />,
    );

    // The default binding follows whatever the default environment points at.
    expect(
      screen.getByText("Fires run whatever the default environment points at when they fire."),
    ).toBeVisible();

    await user.click(screen.getByRole("combobox", { name: "Environment" }));
    await user.click(await screen.findByRole("option", { name: /staging/ }));
    expect(screen.getByText("The next fire runs v3.")).toBeVisible();

    await user.click(screen.getByRole("combobox", { name: "Environment" }));
    await user.click(await screen.findByRole("option", { name: /prod/ }));
    expect(
      screen.getByText(
        "The next fire runs v7 - this environment follows publishes, so the next publish changes what runs.",
      ),
    ).toBeVisible();
  });
});

describe("the default item", () => {
  it("names the environment it currently is, so the list accounts for all of them", async () => {
    // An agent with `production` (default) and `dev` offered `Default` and `dev`,
    // and whoever created `production` read that as an environment missing. The
    // row is still not offered twice: binding to "the default" is a different
    // choice from pinning to whichever row is default today (#1070).
    render(
      <Harness
        environments={[env({ id: "e2", name: "dev", tracks_latest: true })]}
        defaultEnvironment={env({ id: "e1", name: "production", version: 7, is_default: true })}
      />,
    );

    await userEvent.click(screen.getByRole("combobox"));

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("production");
    expect(options[0]).toHaveTextContent("v7");
    expect(options[1]).toHaveTextContent("dev");
  });

  it("says only Default where the agent has no default row to name", async () => {
    render(<Harness environments={[env({ id: "e2", name: "dev" })]} />);

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getAllByRole("option")[0]).toHaveTextContent("Default");
  });
});
