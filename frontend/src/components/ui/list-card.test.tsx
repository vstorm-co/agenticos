import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BookOpen } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ListCard, ListCardEmpty } from "./list-card";

describe("ListCard", () => {
  it("keeps a grid toolbar and its loading state without nesting another surface", () => {
    const { container, rerender } = render(
      <ListCard
        layout="grid"
        namedByPage
        title="Skills"
        counted={null}
        controls={<button>search</button>}
      >
        <p>cards</p>
      </ListCard>,
    );
    expect(container.firstElementChild).toHaveClass("bg-transparent", "border-0", "shadow-none");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(screen.getByRole("button", { name: "search" })).toBeVisible();
    rerender(
      <ListCard layout="grid" namedByPage title="Skills" counted="2 skills">
        <p>cards</p>
      </ListCard>,
    );
    expect(screen.getByText("2 skills")).toBeVisible();
    expect(container.firstElementChild).toHaveClass("bg-transparent", "border-0");
  });

  it("keeps the frame and title in every state, counting once the server answered", () => {
    render(
      <ListCard title="Skills" counted="40 skills">
        <p>rows</p>
      </ListCard>,
    );

    expect(screen.getByText("Skills")).toBeInTheDocument();
    expect(screen.getByText("40 skills")).toBeInTheDocument();
    expect(screen.getByText("rows")).toBeInTheDocument();
  });

  it("draws a skeleton rather than claiming a count nothing has said yet", () => {
    const { container } = render(
      <ListCard title="Keys" counted={null}>
        <p>rows</p>
      </ListCard>,
    );

    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("renders the caller's controls in the header", () => {
    render(
      <ListCard title="Skills" counted="1 skill" controls={<button>search</button>}>
        <p>rows</p>
      </ListCard>,
    );

    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();
  });

  it("leads with the count under a page that names it, keeping the title for a screen reader", () => {
    const { container, rerender } = render(
      <ListCard title="Skills" counted="40 skills" namedByPage controls={<button>search</button>}>
        <p>rows</p>
      </ListCard>,
    );

    expect(screen.getByText("Skills")).toHaveClass("sr-only");
    expect(screen.getByText("40 skills")).toBeVisible();
    expect(screen.getByRole("button", { name: "search" })).toBeInTheDocument();

    rerender(
      <ListCard title="Skills" counted={null} namedByPage>
        <p>rows</p>
      </ListCard>,
    );
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("drops the toolbar over an empty list, leaving the empty state to say so", () => {
    render(
      <ListCard title="Skills" counted="0 skills" namedByPage empty>
        <p>No skills yet</p>
      </ListCard>,
    );

    expect(screen.getByText("0 skills").parentElement).toHaveClass("sr-only");
    expect(screen.getByText("No skills yet")).toBeVisible();
  });
});

describe("ListCard's content padding", () => {
  it("is tighter on a phone by default, and keeps the caller's other classes", () => {
    render(
      <ListCard title="Skills" counted="2" contentClassName="space-y-4">
        <p>body</p>
      </ListCard>,
    );

    expect(screen.getByText("body").parentElement).toHaveClass("p-3", "sm:p-5", "space-y-4");
  });

  it("stays flush when the caller asks for no padding, on every screen", () => {
    // Merged, `p-0` dropped `p-3` but kept `sm:p-5`: a flush table regained an
    // inset from the small breakpoint up.
    render(
      <ListCard title="Runs" counted="2" contentClassName="p-0">
        <p>table</p>
      </ListCard>,
    );

    const content = screen.getByText("table").parentElement;
    expect(content).toHaveClass("p-0");
    expect(content).not.toHaveClass("sm:p-5");
  });

  it("keeps the default on the sides a caller's own padding does not set", () => {
    render(
      <ListCard title="Workspaces" counted="4" contentClassName="pb-6">
        <p>grid</p>
      </ListCard>,
    );

    const content = screen.getByText("grid").parentElement;
    expect(content).toHaveClass("p-5", "pb-6");
    expect(content).not.toHaveClass("sm:p-5");
  });
});

describe("ListCardEmpty", () => {
  it("says what is missing and offers the way out", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <ListCardEmpty
        icon={BookOpen}
        title="No skills yet"
        description="Write one down."
        cta={{ label: "New skill", onClick }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "New skill" }));

    expect(screen.getByText("No skills yet")).toBeInTheDocument();
    expect(screen.getByText("Write one down.")).toBeInTheDocument();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("offers no button when there is nothing the reader may do", () => {
    render(<ListCardEmpty icon={BookOpen} title="Nothing here" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
