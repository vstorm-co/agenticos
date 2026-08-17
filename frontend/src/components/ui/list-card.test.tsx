import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BookOpen } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ListCard, ListCardEmpty } from "./list-card";

describe("ListCard", () => {
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
