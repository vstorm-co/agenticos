/** @vitest-environment node */
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

import { GET as diagnostics } from "./diagnostics/route";
import { GET as updates, POST as updateAction } from "./updates/[[...path]]/route";
import { POST as presence } from "../diagnostics/presence/route";

const routes = [
  ["/admin/diagnostics", diagnostics, "GET"],
  ["/admin/updates", updates, "GET"],
  ["/admin/updates/prepare", updateAction, "POST"],
  ["/admin/updates/apply", updateAction, "POST"],
  ["/admin/updates/cancel", updateAction, "POST"],
  ["/diagnostics/presence", presence, "POST"],
] as const;

afterEach(() => vi.unstubAllGlobals());

it.each(routes)("forwards %s through the authenticated BFF", async (path, handler, method) => {
  const fetch = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  const request = new NextRequest(`http://localhost:3000/api${path}`, {
    method,
    ...(method === "POST" ? { body: "{}", headers: { "Content-Type": "application/json" } } : {}),
  });
  request.cookies.set("agenticos_access_token", "local-session");

  const response = await handler(request);

  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith(
    `http://localhost:8000/api/v1${path}`,
    expect.objectContaining({
      method,
      headers: expect.objectContaining({ Authorization: "Bearer local-session" }),
    }),
  );
});

it.each(routes)("refuses %s without a session", async (path, handler, method) => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const response = await handler(new NextRequest(`http://localhost:3000/api${path}`, { method }));
  expect(response.status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
