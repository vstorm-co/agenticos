import { render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { BackendApiError, backendFetch } from "@/lib/server-api";
import SharedConversationPage from "./page";

vi.mock("next-intl/server", async () => {
  const { createTranslator } = await import("next-intl");
  const { default: messages } = await import("../../../../../messages/en.json");
  return {
    getRequestConfig: vi.fn(),
    getTranslations: ({ namespace }: { namespace: "pages.root" | "chat.rail" }) =>
      createTranslator({ locale: "en", messages, namespace }),
  };
});

vi.mock("@/lib/server-api", async (load) => ({
  ...(await load<typeof import("@/lib/server-api")>()),
  backendFetch: vi.fn(),
}));

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content, inertImages }: { content: string; inertImages?: boolean }) => (
    <span data-inert-images={inertImages}>{content}</span>
  ),
}));

const open = (token = "share-example") =>
  SharedConversationPage({ params: Promise.resolve({ token, locale: "en" }) });

beforeEach(() => vi.resetAllMocks());

it("renders the transcript and passes only agent replies to the Markdown renderer", async () => {
  vi.mocked(backendFetch).mockResolvedValue({
    show_agenticos_attribution: false,
    conversation: {
      title: "Release notes",
      messages: [
        { id: "1", role: "user", content: "Keep `1.2.0` as written.", created_at: null },
        {
          id: "2",
          role: "assistant",
          content:
            "## Summary\n\n- **One change**\n\n![Illustration](https://example.test/report.png)",
          created_at: "2026-11-20T00:00:00Z",
        },
        { id: "3", role: "assistant", content: null, created_at: null },
      ],
    },
  });
  render(await open());

  expect(screen.getByRole("heading", { level: 1, name: "Release notes" })).toBeVisible();
  expect(screen.getByText("Read only")).toBeVisible();
  const [question, answer] = screen
    .getAllByRole("listitem")
    .filter((row) => row.parentElement?.tagName === "OL");
  if (!question || !answer) throw new Error("Missing conversation messages");
  expect(within(question).getByText("User")).toBeVisible();
  expect(question).toHaveTextContent("Keep `1.2.0` as written.");
  expect(within(answer).getByText(/## Summary/)).toHaveAttribute("data-inert-images", "true");
  expect(question.querySelector("[data-inert-images]")).toBeNull();
  expect(screen.queryByRole("contentinfo")).toBeNull();
  expect(backendFetch).toHaveBeenCalledWith("/api/v1/conversations/shared/share-example", {
    cache: "no-store",
  });
});

it("renders an unavailable link without making requests for malformed tokens", async () => {
  render(await open("../private"));
  expect(backendFetch).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Share link not found" })).toBeVisible();
});

it("renders an expired link after the server refuses the token", async () => {
  vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(404, "Not found", null));
  render(await open());
  expect(screen.getByRole("heading", { name: "Share link not found" })).toBeVisible();
});
