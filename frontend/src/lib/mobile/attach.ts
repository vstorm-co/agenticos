/**
 * Photos and files from the phone into a message (#2097): the app's own
 * pickers behind the composer's "+", and its offer of a photo taken a moment
 * ago. Both are drawn by the app; the console is handed only what the person
 * tapped, in the shape something shared with the app arrives in.
 */

import { invokeShell } from "@/lib/desktop/shell";
import { parseShared, type SharedContent } from "@/lib/mobile/shared";

/** Where a file comes from: the tile tapped in the composer's sheet. */
export type AttachSource = "camera" | "photos" | "files";

/**
 * The app's picker for that source - on iOS the camera, the photos or Files at
 * once, on Android its sheet of all three - until the person picks something
 * or puts it away.
 */
export async function openAttachSheet(source: AttachSource): Promise<SharedContent | null> {
  return parseShared(await invokeShell("attach_sheet", { source }));
}

/** A photo just taken, if there is one and the person adds it. */
export async function offerRecentPhoto(): Promise<SharedContent | null> {
  return parseShared(await invokeShell("offer_recent_photo"));
}
