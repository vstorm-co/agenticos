import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { version } from "../../../package.json";
import type { LatestReleaseResponse } from "@/lib/releases";
import { ConsoleVersion } from "./console-version";

const state = vi.hoisted(() => ({ data: undefined as LatestReleaseResponse | undefined }));
vi.mock("@/hooks/use-release-update", () => ({ useReleaseUpdate: () => state }));
beforeEach(() => {
  state.data = undefined;
});
const next = `${version.split(".")[0]}.${Number(version.split(".")[1]) + 1}.0`;
it.each([false, true])(
  "keeps the running version quiet without an update (collapsed=%s)",
  (collapsed) => {
    render(<ConsoleVersion collapsed={collapsed} />);
    expect(screen.getByLabelText(`Console version ${version}`)).toHaveTextContent(`v${version}`);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  },
);
it.each([
  null,
  { version, url: "https://github.com/vstorm-co/agenticos/releases" },
  { version: "0.0.1", url: "https://github.com/vstorm-co/agenticos/releases" },
])("does not flag an absent, equal or older release", (latest) => {
  state.data = { latest };
  render(<ConsoleVersion />);
  expect(screen.queryByRole("button")).toBeNull();
});
it.each([false, true])(
  "opens update information from the highlighted version (collapsed=%s)",
  async (collapsed) => {
    state.data = {
      latest: {
        version: next,
        url: `https://github.com/vstorm-co/agenticos/releases/tag/v${next}`,
      },
    };
    render(<ConsoleVersion collapsed={collapsed} />);
    const button = screen.getByRole("button", { name: `Version ${next} is available` });
    expect(button).toHaveTextContent(`v${version}`);
    expect(screen.getByRole("status")).toHaveTextContent(`Version ${next} is available`);
    await userEvent.click(button);
    expect(screen.getByRole("heading", { name: "Update available" })).toBeVisible();
    expect(
      screen.getByText(`You are using ${version}. AgenticOS ${next} is available.`),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "View release" })).toHaveAttribute(
      "href",
      `https://github.com/vstorm-co/agenticos/releases/tag/v${next}`,
    );
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("link", { name: "View release" })).toBeNull();
    expect(button).toHaveFocus();
  },
);
