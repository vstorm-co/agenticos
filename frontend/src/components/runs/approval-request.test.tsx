import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { ApprovalDetails, ToolMark } from "./approval-request";

function inIntl(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {node}
    </NextIntlClientProvider>,
  );
}

describe("ToolMark - what is asking", () => {
  it("draws a service's own logo in colour where one ships", () => {
    const { container } = inIntl(<ToolMark toolName="notion_notion-search" />);
    expect(container.querySelector("img")).not.toBeNull();
  });

  it("draws a brand's mark where there is no logo, and an initial where there is neither", () => {
    const brand = inIntl(<ToolMark toolName="github_create_issue" />);
    expect(brand.container.querySelector("img")).toBeNull();
    expect(brand.container.querySelector("svg")).not.toBeNull();
    brand.unmount();

    const unknown = inIntl(<ToolMark toolName="acmecorp_do-thing" />);
    expect(unknown.container.querySelector("svg")).toBeNull();
    expect(unknown.container).toHaveTextContent("a");
  });

  it("draws the kind of thing a built-in tool does", () => {
    const { container } = inIntl(<ToolMark toolName="execute" className="size-7" />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("ApprovalDetails - the evidence, folded", () => {
  it("opens on asking, with every value read as text and the empty ones left out", async () => {
    inIntl(
      <ApprovalDetails
        toolName="notion_notion-search"
        args={{
          file_name: "notes.md",
          limit: 3,
          dry_run: false,
          page_url: "",
          tags: ["a", "b"],
          filters: { created: { start: "2026-01-01" } },
          rows: [{ a: 1 }],
        }}
      />,
    );
    expect(screen.queryByText("notes.md")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Details" }));

    expect(screen.getByRole("button", { name: "Details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("File Name")).toBeInTheDocument();
    expect(screen.getByText("notes.md")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("a, b")).toBeInTheDocument();
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
    expect(screen.queryByText("Page Url")).toBeNull();
    expect(screen.getByText("notion_notion-search")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.queryByText("notes.md")).toBeNull();
  });

  it("says a call takes nothing", async () => {
    inIntl(<ApprovalDetails toolName="clock_now" args={{ unused: "" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText("It takes nothing.")).toBeInTheDocument();
  });
});
