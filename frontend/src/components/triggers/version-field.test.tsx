import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { VersionField } from "./version-field";

vi.mock("@/hooks/use-agents", () => ({
  useAllAgentVersions: () => ({
    versions: [
      { id: "v1", version: 1, note: "Original" },
      { id: "v2", version: 2, note: null },
    ],
    isLoading: false,
  }),
}));

function Harness({ initial = null }: { initial?: string | null }) {
  const [version, setVersion] = useState<string | null>(initial);
  const [valid, setValid] = useState(true);
  return (
    <>
      <VersionField agentId="a1" value={version} onChange={setVersion} onValidChange={setValid} />
      <button disabled={!valid}>Save</button>
      <output data-testid="version">{version ?? "following"}</output>
    </>
  );
}

describe("routine version policy", () => {
  it("requires an explicit version before saving a pin and can return to following", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByRole("combobox", { name: "Pinned version" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Version policy" }));
    await user.click(await screen.findByRole("option", { name: "Pin a published version" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Pinned version" }));
    await user.click(await screen.findByRole("option", { name: /v1/ }));
    expect(screen.getByTestId("version")).toHaveTextContent("v1");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    await user.click(screen.getByRole("combobox", { name: "Version policy" }));
    await user.click(await screen.findByRole("option", { name: "Follow published version" }));
    expect(screen.getByTestId("version")).toHaveTextContent("following");
  });

  it("keeps an unavailable recorded pin visible rather than silently choosing latest", async () => {
    render(<Harness initial="missing" />);
    expect(screen.getByRole("combobox", { name: "Pinned version" })).toHaveTextContent(
      "Selected version unavailable",
    );
    expect(screen.getByTestId("version")).toHaveTextContent("missing");
  });
});
