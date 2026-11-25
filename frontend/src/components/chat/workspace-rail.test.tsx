import { fireEvent, render } from "@testing-library/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { WorkspaceRail } from "./workspace-rail";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

beforeEach(() => {
  useBrowserPanelStore.setState({ surface: null, openCallId: null });
});

describe("WorkspaceRail", () => {
  it("opens and closes browser and task panes without an agent", () => {
    const { container } = render(
      <WorkspaceRail
        filesSlot={createRef<HTMLSpanElement>()}
        panelIds={{
          browser: "browser",
          computer: "computer",
          settings: "settings",
          tasks: "tasks",
        }}
      />,
    );
    const buttons = container.querySelectorAll("button");
    const browser = buttons[0]!;
    const tasks = container.querySelector('[data-tour="chat-workspace-tasks"]')!;

    fireEvent.click(browser);
    expect(useBrowserPanelStore.getState().surface).toBe("browser");
    fireEvent.click(browser);
    expect(useBrowserPanelStore.getState().surface).toBeNull();

    fireEvent.click(tasks);
    expect(useBrowserPanelStore.getState().surface).toBe("tasks");
    fireEvent.click(tasks);
    expect(useBrowserPanelStore.getState().surface).toBeNull();
    expect(container.querySelector('[data-tour="chat-agent-settings"]')).toBeNull();
  });

  it("opens the agent settings surface for the selected chat", () => {
    const { container } = render(
      <WorkspaceRail
        filesSlot={createRef<HTMLSpanElement>()}
        hasAgent
        panelIds={{
          browser: "browser",
          computer: "computer",
          settings: "settings",
          tasks: "tasks",
        }}
      />,
    );
    const settings = container.querySelector('[data-tour="chat-agent-settings"]');
    expect(settings).not.toBeNull();

    fireEvent.click(settings!);

    expect(useBrowserPanelStore.getState().surface).toBe("settings");
    fireEvent.click(settings!);
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });
});
