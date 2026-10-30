import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm } from "./forgot-password-form";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { post: vi.fn() },
}));

beforeEach(() => vi.clearAllMocks());

async function submit() {
  render(<ForgotPasswordForm />);
  await userEvent.type(screen.getByLabelText("Email"), "person@example.invalid");
  await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
}

describe("password reset delivery feedback", () => {
  it.each([
    new TypeError("Failed to fetch"),
    new ApiError(429, "Too many requests"),
    new ApiError(503, "Unavailable"),
  ])("keeps the form retryable instead of claiming delivery after %s", async (error) => {
    vi.mocked(apiClient.post).mockRejectedValue(error);
    await submit();
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Send reset link" })).toBeEnabled();
    expect(screen.getByLabelText("Email")).toHaveValue("person@example.invalid");
  });

  it.each([undefined, new ApiError(404, "Not found")])(
    "keeps account existence private for %s",
    async (error) => {
      if (error) vi.mocked(apiClient.post).mockRejectedValue(error);
      else vi.mocked(apiClient.post).mockResolvedValue({});
      await submit();
      expect(await screen.findByText("Check your inbox")).toBeVisible();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});
