import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { ApiUsage } from "./api-usage";

describe("ApiUsage", () => {
  it("gives the base URL, the API reference and the guide", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ApiUsage />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("http://localhost:8000")).toBeInTheDocument();
    expect(screen.getByText("Authorization: Bearer aos_…")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "API reference: every endpoint" })).toHaveAttribute(
      "href",
      "/settings/api-keys/reference",
    );
    expect(screen.getByRole("link", { name: "How to call the API" })).toHaveAttribute(
      "href",
      expect.stringContaining("/api/#organization-api-keys"),
    );
  });
});
