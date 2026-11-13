import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { NextIntlClientProvider, useFormatter, useTimeZone } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";

import { BrowserTimeZone } from "./browser-time-zone";

// The global setup's `useFormatter` ignores the provider's zone, which is the
// whole of what this file tests.
vi.mock("next-intl", async (importOriginal) => importOriginal());

const PUBLISHED = new Date("2026-11-10T09:35:00Z");

function Probe() {
  const format = useFormatter();
  return (
    <p>
      {useTimeZone()} {format.dateTime(PUBLISHED, { timeStyle: "short", hourCycle: "h23" })}
    </p>
  );
}

function page() {
  return (
    <NextIntlClientProvider locale="en" timeZone="UTC" messages={{}}>
      <BrowserTimeZone>
        <Probe />
      </BrowserTimeZone>
    </NextIntlClientProvider>
  );
}

afterEach(() => vi.restoreAllMocks());

it("formats dates in the reader's own time zone once in the browser", () => {
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
    ...new Intl.DateTimeFormat("en", { timeZone: "Europe/Warsaw" }).resolvedOptions(),
  });
  render(page());
  expect(screen.getByText("Europe/Warsaw 10:35")).toBeInTheDocument();
});

it("renders the server's zone on the server, so hydration matches its HTML", () => {
  expect(renderToString(page()).replaceAll("<!-- -->", "")).toContain("UTC 09:35");
});
