import type { WebSocketRoute } from "@playwright/test";
import { test, expect } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE, reducedMotion: "reduce" });

for (const width of [1440, 390]) {
  test(`answer sources toggle and switch ownership at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/chat?answerer=agenticos");
    await expect(
      page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
    ).toBeVisible();
    const created = await page.request.post("/api/conversations", {
      data: { title: `Source panel toggle ${width}` },
    });
    expect(created.ok()).toBe(true);
    const body: unknown = await created.json();
    if (!body || typeof body !== "object" || !("id" in body) || typeof body.id !== "string")
      throw new Error("Expected a persisted conversation");
    const id = body.id;
    try {
      const history = await page.request.post(`/api/conversations/${id}/messages`, {
        data: { role: "user", content: "Source panel regression fixture" },
      });
      expect(history.ok()).toBe(true);
      let socket: WebSocketRoute | undefined;
      await page.routeWebSocket(/\/api\/v1\/ws\/agent/, (connection) => {
        socket = connection;
      });
      await page.goto(`/chat?id=${id}`);
      await expect(page.getByText("Live", { exact: true })).toBeVisible();
      await expect.poll(() => !!socket).toBe(true);
      await expect(
        page.getByText("Source panel regression fixture", { exact: true }),
      ).toBeVisible();
      const send = (type: string, data: object) => {
        if (!socket) throw new Error("Expected a connected socket");
        socket.send(JSON.stringify({ type, data }));
      };
      // Control only model frames: use the real chat layout and authenticated backend.
      for (const title of ["First source", "Second source"]) {
        send("model_request_start", {});
        send("tool_call", { tool_name: "web_search", tool_call_id: title, args: { query: title } });
        send("tool_result", {
          tool_call_id: title,
          content: JSON.stringify({
            kind: "web_search",
            results: [{ title, url: "https://github.com/vstorm-co/agenticos" }],
          }),
        });
        send("final_result", { output: `Answer from ${title}.` });
        send("complete", {});
        await expect(page.getByText(`Answer from ${title}.`, { exact: true })).toBeVisible();
      }
      const triggers = page.getByRole("button", { name: "1 source", exact: true });
      await expect(triggers).toHaveCount(2);
      const close = page.getByRole("button", { name: "Close sources panel", exact: true });
      await triggers.nth(1).click();
      await expect(close).toBeVisible();
      await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "true");
      if (width === 1440) {
        await triggers.nth(1).click();
        await expect(close).toHaveCount(0);
        await triggers.nth(1).press("Enter");
        await expect(close).toBeVisible();
        await triggers.nth(0).click();
        await expect(triggers.nth(0)).toHaveAttribute("aria-expanded", "true");
        await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "false");
      }
      await close.click();
      await expect(close).toHaveCount(0);
      await expect(triggers.nth(0)).toHaveAttribute("aria-expanded", "false");
      await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "false");
      await triggers.nth(1).click();
      await expect(close).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(close).toHaveCount(0);
    } finally {
      const deleted = await page.request.delete(`/api/conversations/${id}`);
      expect(deleted.ok()).toBe(true);
    }
  });
}
