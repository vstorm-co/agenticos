import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { EventOptions, eventOptionsValid } from "./event-options";
import type { EventSource } from "@/types/triggers";

function Editor({
  source,
  initial = {},
}: {
  source: EventSource;
  initial?: Record<string, unknown>;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <>
      <EventOptions source={source} config={config} onChange={setConfig} />
      <output data-testid="config">{JSON.stringify(config)}</output>
    </>
  );
}

describe("EventOptions", () => {
  it.each(["google_drive", "microsoft_files"] as const)(
    "lets %s include the connected user's own changes",
    async (source) => {
      render(<Editor source={source} />);
      await userEvent.click(screen.getByRole("checkbox", { name: "Include my own changes" }));
      expect(screen.getByTestId("config")).toHaveTextContent('"include_own_changes":true');
      await userEvent.click(screen.getByRole("checkbox", { name: "Include my own changes" }));
      expect(screen.getByTestId("config")).toHaveTextContent('"include_own_changes":false');
    },
  );
  it("edits the Microsoft file name filter", () => {
    render(<Editor source="microsoft_files" initial={{ name_contains: 1 }} />);
    const input = screen.getByLabelText("File name contains");
    fireEvent.change(input, { target: { value: "invoice" } });
    expect(input).toHaveValue("invoice");
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("config")).not.toHaveTextContent("name_contains");
  });
  it("edits a comment mention independently of its preset", () => {
    render(<Editor source="github" initial={{ event: "issue_comment", mention: "@agent" }} />);
    fireEvent.change(screen.getByLabelText("Mention phrase"), { target: { value: "@reviewer" } });
    expect(screen.getByTestId("config")).toHaveTextContent('"mention":"@reviewer"');
  });
  it.each(["push", "pull_request", "workflow_run"])("edits the %s branches", (event) => {
    render(<Editor source="github" initial={{ event, branches: ["main"] }} />);
    const input = screen.getByLabelText("Branches (comma-separated)");
    expect(input).toHaveValue("main");
    fireEvent.change(input, { target: { value: "master, develop,," } });
    expect(screen.getByTestId("config")).toHaveTextContent('["master","develop"]');
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("config")).not.toHaveTextContent("branches");
  });
  it.each(["google_calendar", "outlook_calendar"] as const)(
    "edits the %s lead and audience",
    async (source) => {
      render(<Editor source={source} />);
      const input = screen.getByLabelText("Minutes before the meeting");
      expect(input).toHaveValue(15);
      fireEvent.change(input, { target: { value: "60" } });
      expect(input).toHaveValue(60);
      await userEvent.click(
        screen.getByRole("checkbox", { name: "Only meetings with external attendees" }),
      );
      expect(screen.getByTestId("config")).toHaveTextContent('"external_only":true');
    },
  );
  it("offers Gmail's label filter without unrelated switches", () => {
    render(<Editor source="gmail" />);
    expect(screen.getByLabelText("Gmail label ID")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("calendar lead validation", () => {
  it.each([
    [undefined, true],
    [5, true],
    [120, true],
    [0, false],
    [121, false],
    [1.5, false],
    ["15", false],
  ])("validates %s", (minutes_before, expected) => {
    expect(eventOptionsValid({ minutes_before })).toBe(expected);
  });
});

describe("GitHub author filters", () => {
  it.each([{}, { actions: ["opened"] }])(
    "shows the effective default for legacy configs %j",
    (initial) => {
      render(<Editor source="github" initial={initial} />);
      expect(
        screen.getByRole("combobox", { name: "Whose events can start this routine" }),
      ).toHaveValue("members");
      expect(screen.getByText(/OWNER, MEMBER and COLLABORATOR/)).toBeVisible();
      expect(screen.getByTestId("config")).not.toHaveTextContent('"authors"');
    },
  );
  it.each(["members", "contributors", "anyone"])(
    "edits %s while preserving the other filters",
    async (authors) => {
      render(
        <Editor
          source="github"
          initial={{
            event: "issue_comment",
            authors: "anyone",
            mention: "@agent",
            ignore_login: "agent-bot",
          }}
        />,
      );
      await userEvent.selectOptions(
        screen.getByRole("combobox", { name: "Whose events can start this routine" }),
        authors,
      );
      expect(JSON.parse(screen.getByTestId("config").textContent ?? "{}")).toEqual({
        event: "issue_comment",
        authors,
        mention: "@agent",
        ignore_login: "agent-bot",
      });
    },
  );
  it.each(["push", "workflow_run", "release"])(
    "does not offer an inactive author filter for %s",
    (event) => {
      render(<Editor source="github" initial={{ event }} />);
      expect(
        screen.queryByRole("combobox", { name: "Whose events can start this routine" }),
      ).toBeNull();
    },
  );
});
