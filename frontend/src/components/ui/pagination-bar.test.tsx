import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { PaginationBar } from "./pagination-bar";

function renderBar(props: Partial<Parameters<typeof PaginationBar>[0]> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <PaginationBar page={0} pageSize={50} total={120} onPage={() => {}} {...props} />
    </NextIntlClientProvider>,
  );
}

describe("PaginationBar", () => {
  it("renders nothing over an empty list", () => {
    const { container } = renderBar({ total: 0 });

    expect(container).toBeEmptyDOMElement();
  });

  it("says which slice of the whole it is showing", () => {
    renderBar({ page: 1, pageSize: 50, total: 120 });

    expect(screen.getByText("51–100 of 120")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("asks for the next page and refuses to walk off either end", async () => {
    const user = userEvent.setup();
    const onPage = vi.fn();
    renderBar({ page: 0, onPage });

    expect(screen.getByRole("button", { name: messages.ui.previousPage })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: messages.ui.nextPage }));

    expect(onPage).toHaveBeenCalledWith(1);
  });

  it("holds both buttons while a page is loading", () => {
    renderBar({ page: 1, isLoading: true });

    expect(screen.getByRole("button", { name: messages.ui.previousPage })).toBeDisabled();
    expect(screen.getByRole("button", { name: messages.ui.nextPage })).toBeDisabled();
  });

  it("disables next on the last page", () => {
    renderBar({ page: 2, pageSize: 50, total: 120 });

    expect(screen.getByRole("button", { name: messages.ui.nextPage })).toBeDisabled();
  });
});
