import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MainViewport } from "./main-viewport";

let path = "/en/chat";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

it("omits the empty native strip and page padding for chat in every locale", () => {
  const view = render(<MainViewport>Chat</MainViewport>);
  for (const route of ["/en/chat", "/pl/chat", "/de/chat", "/chat"]) {
    path = route;
    view.rerender(<MainViewport>Chat</MainViewport>);
    expect(view.container.querySelector(".window-drag-strip")).toBeNull();
    expect(view.container.querySelector(".chat-window-drag-region")).toHaveAttribute(
      "data-tauri-drag-region",
    );
    expect(screen.getByRole("main")).toHaveClass("p-0");
    expect(screen.getByRole("main")).not.toHaveClass("pt-(--page-inset-top)");
  }
});

it("restores the ordinary page frame when leaving chat", () => {
  path = "/en/chat";
  const view = render(<MainViewport>Page</MainViewport>);
  for (const route of ["/en/agents", "/en/chatty"]) {
    path = route;
    view.rerender(<MainViewport>Page</MainViewport>);
    expect(view.container.querySelector(".window-drag-strip")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveClass("pt-(--page-inset-top)");
    expect(view.container.querySelector(".chat-window-drag-region")).toBeNull();
    expect(screen.getByRole("main")).not.toHaveClass("p-0");
  }
});
