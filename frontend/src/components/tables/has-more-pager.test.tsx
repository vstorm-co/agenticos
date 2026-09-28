import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HasMorePager } from "./has-more-pager";

describe("HasMorePager", () => {
  it("disables previous on the first page", () => {
    render(<HasMorePager page={0} hasMore={true} onPage={vi.fn()} />);
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
  });

  it("disables next when there is no more", () => {
    render(<HasMorePager page={1} hasMore={false} onPage={vi.fn()} />);
    expect(screen.getByRole("button", { name: /previous/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("disables both while loading", () => {
    render(<HasMorePager page={1} hasMore={true} isLoading onPage={vi.fn()} />);
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("steps forward and never below zero going back", async () => {
    const onPage = vi.fn();
    const user = userEvent.setup();
    render(<HasMorePager page={1} hasMore={true} onPage={onPage} />);

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(onPage).toHaveBeenCalledWith(2);

    await user.click(screen.getByRole("button", { name: /previous/i }));
    expect(onPage).toHaveBeenCalledWith(0);
  });
});
