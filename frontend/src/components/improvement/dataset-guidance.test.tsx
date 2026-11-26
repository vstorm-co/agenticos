import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { DatasetGuidance } from "./dataset-guidance";
import messages from "../../../messages/en.json";
import type { HelperGuidance } from "@/types/improvement";

function show(guidance: HelperGuidance) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <DatasetGuidance guidance={guidance} />
    </NextIntlClientProvider>,
  );
}

describe("the dataset's guidance at the start of Improve", () => {
  it("shows the guidance and the member who last changed it", () => {
    show({
      text: "Prefer the shortest correct answer.",
      updated_at: "2026-11-20T10:00:00Z",
      updated_by_name: "Ada Lovelace",
    });

    expect(screen.getByText("Prefer the shortest correct answer.")).toBeInTheDocument();
    expect(screen.getByText(/Last changed by Ada Lovelace on/)).toBeInTheDocument();
  });

  it("says a former member changed it without naming anybody", () => {
    show({ text: "Be brief.", updated_by_former_member: true });

    expect(screen.getByText("Last changed by a former member.")).toBeInTheDocument();
  });

  it("shows guidance an older dataset recorded without an author", () => {
    show({ text: "Be brief." });

    expect(screen.getByText("Be brief.")).toBeInTheDocument();
    expect(screen.queryByText(/Last changed/)).toBeNull();
  });
});
