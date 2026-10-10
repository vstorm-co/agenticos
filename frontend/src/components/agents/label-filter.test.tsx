import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LabelFilter } from "./label-filter";

function renderFilter(options: string[], selected: string[], onChange = vi.fn(), max = 20) {
  render(
    <LabelFilter
      options={options}
      selected={selected}
      onChange={onChange}
      ariaLabel="Filter by tag"
      allLabel="All tags"
      countLabel={(count) => `${count} tags`}
      clearLabel="Clear filter"
      max={max}
    />,
  );
  return onChange;
}

describe("LabelFilter", () => {
  it("renders nothing when there is nothing to pick", () => {
    renderFilter([], []);

    expect(screen.queryByRole("button", { name: "Filter by tag" })).toBeNull();
  });

  it("keeps a picked value the choices no longer carry, so it can be unpicked", async () => {
    const onChange = renderFilter(["eu"], ["legacy"]);

    expect(screen.getByRole("button", { name: "Filter by tag" })).toHaveTextContent("legacy");
    await userEvent.click(screen.getByRole("button", { name: "Filter by tag" }));
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "legacy" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("adds an unpicked value to the selection", async () => {
    const onChange = renderFilter(["eu", "vip"], ["eu"]);

    await userEvent.click(screen.getByRole("button", { name: "Filter by tag" }));
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "vip" }));

    expect(onChange).toHaveBeenCalledWith(["eu", "vip"]);
  });

  it("disables the unpicked choices once the API's cap is reached", async () => {
    // Past the cap the server drops the extra picks without saying so, so a
    // checked box past it would claim a filter that does nothing (#1930).
    const onChange = renderFilter(["eu", "us", "vip"], ["eu", "us"], vi.fn(), 2);

    await userEvent.click(screen.getByRole("button", { name: "Filter by tag" }));
    const vip = await screen.findByRole("menuitemcheckbox", { name: "vip" });

    expect(vip).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(vip);
    expect(onChange).not.toHaveBeenCalled();
    // A picked value can still be unpicked.
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "eu" }));
    expect(onChange).toHaveBeenCalledWith(["us"]);
  });
});
