import Link from "next/link";
import { render, waitFor } from "@testing-library/react";
import { useRef, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BrandingProvider } from "@/components/branding/branding-provider";
import { BUILT_IN_BRANDING } from "@/lib/branding";
import { useConsoleTitle } from "./use-console-title";

let pathname = "/agents";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

function Page({ children }: { children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  useConsoleTitle(main);
  return <main ref={main}>{children}</main>;
}

beforeEach(() => {
  pathname = "/agents";
  document.title = "Initial title";
});
afterEach(() => vi.restoreAllMocks());

it("names a loading destination, then uses the heading when data arrives", async () => {
  const { rerender } = render(<Page>Loading</Page>);
  expect(document.title).toBe("Agents | agenticos");
  rerender(
    <Page>
      <h1>Support agent</h1>
    </Page>,
  );
  await waitFor(() => expect(document.title).toBe("Support agent | agenticos"));
  rerender(
    <Page>
      <h1>Billing agent</h1>
    </Page>,
  );
  await waitFor(() => expect(document.title).toBe("Billing agent | agenticos"));
});

it("includes the active page section and follows client navigation", async () => {
  const { rerender } = render(
    <Page>
      <h1>Settings</h1>
      <nav>
        <Link href="/settings/profile" aria-current="page">
          Appearance
        </Link>
      </nav>
    </Page>,
  );
  expect(document.title).toBe("Appearance — Settings | agenticos");
  pathname = "/chat";
  rerender(<Page>Conversation</Page>);
  await waitFor(() => expect(document.title).toBe("Chat | agenticos"));
});

it("updates an active section without duplicating the page heading", async () => {
  const { rerender } = render(
    <Page>
      <h1>Settings</h1>
      <nav>
        <Link href="/settings/profile" aria-current="page">
          Profile
        </Link>
      </nav>
    </Page>,
  );
  expect(document.title).toBe("Profile — Settings | agenticos");
  rerender(
    <Page>
      <h1>Settings</h1>
      <nav>
        <Link href="/settings/profile" aria-current="page">
          Settings
        </Link>
      </nav>
    </Page>,
  );
  await waitFor(() => expect(document.title).toBe("Settings | agenticos"));
});

it("uses the deployment name and falls back to it for an unknown destination", () => {
  pathname = "/unknown";
  render(
    <BrandingProvider branding={{ ...BUILT_IN_BRANDING, appName: "Acme AI" }}>
      <Page>Unavailable</Page>
    </BrandingProvider>,
  );
  expect(document.title).toBe("Acme AI");
});

it("ignores streamed content and disconnects when the console unmounts", async () => {
  const { rerender, unmount } = render(
    <Page>
      <h1>Chat</h1>
      <p>Hello</p>
    </Page>,
  );
  const writes = vi.spyOn(document, "title", "set");
  rerender(
    <Page>
      <h1>Chat</h1>
      <p>Hello, world</p>
    </Page>,
  );
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  expect(writes).not.toHaveBeenCalled();
  unmount();
  document.body.appendChild(document.createElement("h1"));
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  expect(writes).not.toHaveBeenCalled();
});

it("keeps the destination title when layout metadata arrives after hydration", async () => {
  render(
    <Page>
      <h1>Agents</h1>
    </Page>,
  );
  document.title = "Default deployment metadata";
  await waitFor(() => expect(document.title).toBe("Agents | agenticos"));
});

it("does nothing when the console viewport is not mounted", () => {
  function Absent() {
    useConsoleTitle(useRef<HTMLElement>(null));
    return null;
  }
  render(<Absent />);
  expect(document.title).toBe("Initial title");
});

it("falls back after a heading is removed without changing destinations", async () => {
  const { rerender } = render(
    <Page>
      <h1>Billing agent</h1>
    </Page>,
  );
  rerender(<Page>Loading another agent</Page>);
  await waitFor(() => expect(document.title).toBe("Agents | agenticos"));
});

it("normalizes line breaks in visible compound headings", () => {
  render(
    <Page>
      <h1
        ref={(node) => {
          if (node)
            Object.defineProperty(node, "innerText", {
              value: "Wednesday\nGood evening",
              configurable: true,
            });
        }}
      >
        WednesdayGood evening
      </h1>
    </Page>,
  );
  expect(document.title).toBe("Wednesday Good evening | agenticos");
});

it("handles a heading cleared before queued text mutations are delivered", async () => {
  const { container } = render(
    <Page>
      <h1>Agent</h1>
    </Page>,
  );
  const heading = container.querySelector("h1");
  const text = heading?.firstChild;
  if (!heading || !text) throw new Error("Missing heading text");
  text.textContent = "Renaming";
  heading.replaceChildren();
  await waitFor(() => expect(document.title).toBe("Agents | agenticos"));
});

it("uses a heading when the loaded page arrives inside a section", async () => {
  const { rerender } = render(<Page>Loading</Page>);
  rerender(
    <Page>
      <section>
        <h1>Support agent</h1>
        <p>Instructions</p>
      </section>
    </Page>,
  );
  await waitFor(() => expect(document.title).toBe("Support agent | agenticos"));
});
