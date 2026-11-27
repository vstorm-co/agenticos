import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { saveBlob } from "@/lib/file-access";
import type { MergeFile } from "@/types/skill-merge";
import { MergeFiles } from "./merge-files";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const VERSIONS = { base: "v-base", fork: "v-fork", main: "v-main" };
const BODIES: Record<string, string> = {
  "v-base": "Step one.\n",
  "v-fork": "Step one.\nStep from the fork.\n",
  "v-main": "Step one.\nStep from main.\n",
};

function side(size_bytes = 20, description: string | null = null) {
  return { description, size_bytes };
}

function file(overrides: Partial<MergeFile> = {}): MergeFile {
  return {
    name: "scripts/steps.md",
    state: "conflict",
    base: side(),
    fork: side(),
    main: side(),
    take: null,
    ...overrides,
  };
}

function serve(bodies: Record<string, string> = BODIES) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    const version = path.split("/")[4]!;
    if (!(version in bodies)) throw new ApiError(404, "File not found");
    return { name: "scripts/steps.md", description: null, content: bodies[version] };
  });
}

function mount(files: MergeFile[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MergeFiles
      skillId="k1"
      versions={VERSIONS}
      files={files}
      editable
      saving={false}
      onPick={vi.fn()}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
}

const show = () => userEvent.click(screen.getByRole("button", { name: "Show what changed" }));

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

it("says what each side holds before anything is read", () => {
  mount([file({ fork: side(2048, "Steps the fork rewrote") })]);
  expect(screen.getByText("Where both started: 20 B")).toBeInTheDocument();
  expect(screen.getByText("Fork: 2.0 KB")).toBeInTheDocument();
  expect(screen.getByText("Steps the fork rewrote")).toBeInTheDocument();
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("shows what each side of a conflict changed, read from each side's version", async () => {
  mount([file()]);
  await show();

  expect(await screen.findByText("What the fork changed")).toBeInTheDocument();
  expect(screen.getByText("What main changed")).toBeInTheDocument();
  expect(screen.getByText("Step from the fork.")).toBeInTheDocument();
  expect(screen.getByText("Step from main.")).toBeInTheDocument();
  expect(apiClient.get).toHaveBeenCalledWith(
    "/skills/k1/versions/v-fork/resources/scripts/steps.md",
  );
  await userEvent.click(screen.getByRole("button", { name: "Hide what changed" }));
  expect(screen.queryByText("What the fork changed")).not.toBeInTheDocument();
});

it("opens a change only one side made, and a file only that side added", async () => {
  mount([
    file({ state: "main", take: "main" }),
    file({ name: "new.md", state: "fork", base: null, main: null, take: "fork" }),
  ]);
  const [changed, added] = screen
    .getAllByRole("listitem")
    .filter((row) => row.querySelector("button"));
  expect(within(added!).getByText("Where both started: no such file")).toBeInTheDocument();
  expect(within(added!).getByText("Main: no such file")).toBeInTheDocument();

  await userEvent.click(within(changed!).getByRole("button", { name: "Show what changed" }));
  expect(await within(changed!).findByText("Step from main.")).toBeInTheDocument();
  expect(within(changed!).queryByText("What the fork changed")).not.toBeInTheDocument();

  await userEvent.click(within(added!).getByRole("button", { name: "Show what changed" }));
  expect(await within(added!).findByText("Step from the fork.")).toBeInTheDocument();
  expect(apiClient.get).not.toHaveBeenCalledWith("/skills/k1/versions/v-base/resources/new.md");
});

it("offers a file too large to compare as a download of each side, without reading it", async () => {
  mount([file({ main: side(300 * 1024) })]);
  await show();

  expect(screen.getByText(/Too large to compare here/)).toBeInTheDocument();
  expect(apiClient.get).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Download main's" }));
  await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "steps.md"));
  expect(apiClient.get).toHaveBeenCalledWith(
    "/skills/k1/versions/v-main/resources/scripts/steps.md",
  );
});

it("offers a file that is not text as a download instead of a diff", async () => {
  serve({ ...BODIES, "v-fork": "PK\u0003\u0004\u0000\u0000binary" });
  mount([file()]);
  await show();

  expect(await screen.findByText(/Not text, so it cannot be compared here/)).toBeInTheDocument();
  expect(screen.queryByText("What the fork changed")).not.toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: /^Download/ }).map((button) => button.textContent),
  ).toEqual(["Download where both started", "Download the fork's", "Download main's"]);
});

it("says a side could not be read and reads it again", async () => {
  const { "v-main": _main, ...withoutMain } = BODIES;
  serve(withoutMain);
  mount([file()]);
  await show();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The file could not be read. File not found",
  );
  serve();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Step from main.")).toBeInTheDocument();
});

it("says when a download could not be read", async () => {
  mount([file({ main: side(300 * 1024) })]);
  await show();
  vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(500, "Server error"));
  await userEvent.click(screen.getByRole("button", { name: "Download main's" }));

  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Server error"));
  expect(saveBlob).not.toHaveBeenCalled();
});
