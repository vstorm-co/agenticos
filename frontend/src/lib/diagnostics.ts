import { z } from "zod";

import { apiClient } from "@/lib/api-client";

export const diagnosticsStatusSchema = z.object({
  enabled: z.boolean(),
  collector: z.string(),
  instance_id: z.string().nullable(),
  last_attempt: z.number().nullable(),
  last_success: z.number().nullable(),
  last_error: z.enum(["transport", "rejected"]).nullable(),
});

const claimSchema = z
  .object({
    endpoint: z.url(),
    event: z
      .object({
        signature: z.string().length(88),
        payload: z
          .object({
            protocol: z.literal(1),
            kind: z.literal("presence"),
            instance_id: z.string().regex(/^[a-f0-9]{64}$/),
            event_id: z.string().regex(/^[a-f0-9]{32}$/),
            at: z.number().int(),
            user_id: z.string().regex(/^[a-f0-9]{64}$/),
            surface: z.enum(["web", "desktop", "mobile"]),
            expires_at: z.number().int(),
          })
          .strict(),
      })
      .strict(),
  })
  .strict()
  .nullable();

export async function sendPresence(
  surface: "web" | "desktop" | "mobile",
  origin: string,
  signal: AbortSignal,
): Promise<"sent" | "waiting"> {
  const claim = claimSchema.parse(
    await apiClient.post<unknown>("/diagnostics/presence", { surface }, { signal }),
  );
  if (!claim || signal.aborted) return "waiting";
  const endpoint = new URL(claim.endpoint);
  if (
    endpoint.origin !== new URL(origin).origin ||
    endpoint.pathname !== "/v1/presence" ||
    endpoint.search ||
    endpoint.username ||
    endpoint.password
  ) {
    // i18n-exempt: internal protocol error, caught without displaying it to the user
    throw new Error("Unexpected diagnostic collector endpoint");
  }
  const response = await fetch(endpoint, {
    method: "POST",
    body: JSON.stringify(claim.event),
    signal,
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    referrerPolicy: "no-referrer",
    redirect: "error",
  });
  // i18n-exempt: internal transport error, caught without displaying it to the user
  if (!response.ok) throw new Error("Diagnostic presence was not accepted");
  return "sent";
}
