import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import type { OpenApiDocument } from "@/lib/openapi/reference";
import { ApiReference } from "./api-reference";

const useOpenApi = vi.fn();
vi.mock("@/hooks", () => ({ usePublicOpenApi: () => useOpenApi() }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

const DOCUMENT: OpenApiDocument = {
  info: { title: "public", version: "0.0.535" },
  paths: {
    "/api/v1/agents/{agent_id}/run": {
      post: {
        tags: ["agents"],
        summary: "Run Agent",
        description: "Run a published agent and return its answer.",
        operationId: "run_agent",
        parameters: [{ name: "agent_id", in: "path", required: true, schema: { type: "string" } }],
        requestBody: {
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["prompt"],
                properties: { prompt: { type: "string" } },
              },
            },
          },
        },
        responses: { "200": { description: "Successful Response" } },
      },
    },
    "/api/v1/ml/services": {
      get: { tags: ["ml-services"], summary: "List Services", operationId: "list_services" },
    },
    "/api/v1/upload": {
      put: {
        tags: ["ml-services"],
        summary: "Upload",
        operationId: "upload",
        requestBody: { content: { "application/json": { schema: { type: "string" } } } },
      },
    },
  },
};

function renderReference(state: Partial<ReturnType<typeof useOpenApi>> = {}) {
  useOpenApi.mockReturnValue({
    document: DOCUMENT,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...state,
  });
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ApiReference />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useOpenApi.mockReset());
afterEach(() => vi.useRealTimers());

describe("ApiReference", () => {
  it("lists every group with its endpoints and its count", () => {
    renderReference();

    expect(screen.getByText("version 0.0.535", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Agents\s*1$/ })).toHaveAttribute(
      "href",
      "#group-agents",
    );
    expect(screen.getByRole("link", { name: /^ML services\s*2$/ })).toBeInTheDocument();
    expect(screen.getByText("/api/v1/agents/{agent_id}/run")).toBeInTheDocument();
    expect(screen.getByText("2 endpoints")).toBeInTheDocument();
  });

  it("shows an endpoint's description, parameters, body, responses and a curl call", () => {
    renderReference();

    expect(screen.getByText("Run a published agent and return its answer.")).toBeInTheDocument();
    expect(screen.getByText("agent_id")).toBeInTheDocument();
    expect(screen.getByText("prompt")).toBeInTheDocument();
    expect(screen.getByText("Successful Response")).toBeInTheDocument();
    expect(screen.getAllByText(/curl -X POST/)[0]).toBeInTheDocument();
    // A body that is not an object names its type and draws no field table.
    expect(screen.getAllByText("string").length).toBeGreaterThan(0);
  });

  it("narrows to the endpoints a search matches, and says when none does", async () => {
    renderReference();

    await userEvent.type(screen.getByRole("textbox", { name: "Search endpoints" }), "services");
    expect(screen.queryByText("/api/v1/agents/{agent_id}/run")).not.toBeInTheDocument();
    expect(screen.getByText("/api/v1/ml/services")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Search endpoints" }), "nothing");
    expect(screen.getByText("No endpoint matches “servicesnothing”.")).toBeInTheDocument();
  });

  it("copies a curl call and says so for a moment", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderReference();

    await userEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]!);
    expect(writeText).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(1600);
    });
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("draws a placeholder while the document loads", () => {
    renderReference({ document: null, isLoading: true });
    expect(screen.getByText("API reference")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    expect(screen.queryByText("version 0.0.535", { exact: false })).not.toBeInTheDocument();
    expect(document.querySelector(".lg\\:w-56")).toBeInTheDocument();
  });

  it("says the document could not be loaded, and retries", async () => {
    const refetch = vi.fn();
    renderReference({ document: null, error: new Error("boom"), refetch });

    expect(screen.getByText("The API reference could not be loaded.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
