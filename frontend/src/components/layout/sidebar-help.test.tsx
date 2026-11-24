import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { version } from "../../../package.json";
import { DOCS_URL, LEARN_URL } from "@/lib/help-links";
import { SidebarHelp } from "./sidebar-help";

it.each([false, true])(
  "offers docs, the Learn track and a pre-filled report (collapsed=%s)",
  async (collapsed) => {
    render(<SidebarHelp collapsed={collapsed} />);

    await userEvent.click(screen.getByRole("button", { name: "Help" }));

    expect(screen.getByRole("link", { name: /Documentation/ })).toHaveAttribute("href", DOCS_URL);
    expect(screen.getByRole("link", { name: /Learn/ })).toHaveAttribute("href", LEARN_URL);
    expect(screen.getByRole("link", { name: /Report a problem/ })).toHaveAttribute(
      "href",
      `https://github.com/t3grp/agenticos/issues/new?template=bug_report.yml&version=v${version}`,
    );
    expect(
      screen.getByText("Opens a public GitHub issue with your version filled in"),
    ).toBeInTheDocument();
    expect(screen.getByText(`Reports include console version v${version}`)).toBeInTheDocument();
  },
);

it("is an icon alone on the rail", () => {
  render(<SidebarHelp collapsed />);

  expect(screen.getByRole("button", { name: "Help" })).toHaveTextContent("");
});
