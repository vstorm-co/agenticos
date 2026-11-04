import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { expect, test } from "./fixtures";

const ADDRESS = "http://localhost:3210/";
const NOTICE = "Could not load http://localhost:3210. Check your connection.";

for (const recovering of [false, true]) {
  test(`native server form ${recovering ? "recovers a stalled load" : "starts with the welcome screen"}`, async ({
    page,
  }) => {
    const [html, script, styles] = await Promise.all(
      ["index.html", "onboarding.js", "onboarding.css"].map((name) =>
        readFile(resolve("../mobile/ui", name), "utf8"),
      ),
    );
    await page.addInitScript(
      ({ address, notice }) => {
        Object.assign(window, {
          __TAURI__: {
            core: {
              invoke: async (command: string, args?: { url: string }) => {
                if (command === "server_url") return address;
                if (command === "startup_notice") return notice;
                if (command === "connect" && args?.url === address) throw "Still offline";
                throw new Error(`Unexpected native request: ${command}`);
              },
            },
          },
        });
      },
      { address: ADDRESS, notice: recovering ? NOTICE : null },
    );
    await page.route("http://onboarding.test/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/") await route.fulfill({ contentType: "text/html", body: html });
      else if (path === "/onboarding.js")
        await route.fulfill({ contentType: "text/javascript", body: script });
      else if (path === "/onboarding.css")
        await route.fulfill({ contentType: "text/css", body: styles });
      else await route.abort();
    });
    await page.goto("http://onboarding.test/");
    const field = page.getByRole("textbox", { name: "Server address" });
    if (!recovering) {
      await expect(page.getByRole("button", { name: "Scan a code" })).toBeVisible();
      await expect(field).toBeHidden();
      await page.getByRole("button", { name: "Enter the address" }).tap();
      await expect(field).toBeFocused();
    } else {
      await expect(page.getByRole("alert").filter({ visible: true })).toHaveText(NOTICE);
      await expect(field).not.toBeFocused();
    }
    await expect(field).toHaveValue(ADDRESS);
    const submit = page.getByRole("button", { name: "Continue" });
    await submit.tap();
    await expect(page.getByRole("alert").filter({ visible: true })).toHaveText("Still offline");
    await expect(submit).toBeEnabled();
    await page.getByRole("button", { name: "Back", exact: true }).tap();
    await expect(page.getByRole("button", { name: "Scan a code" })).toBeVisible();
  });
}
