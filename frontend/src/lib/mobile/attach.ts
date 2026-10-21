/**
 * Photos and files from the phone into a message (#2097): the app's own
 * attach sheet behind the composer's "+", and its offer of a photo taken a
 * moment ago. Both are drawn by the app; the console is handed only what the
 * person tapped, in the shape something shared with the app arrives in.
 */

import { invokeShell } from "@/lib/desktop/shell";
import { parseShared, type SharedContent } from "@/lib/mobile/shared";

/** The sheet, until the person picks something or puts it away. */
export async function openAttachSheet(): Promise<SharedContent | null> {
  return parseShared(await invokeShell("attach_sheet"));
}

/** A photo just taken, if there is one and the person adds it. */
export async function offerRecentPhoto(): Promise<SharedContent | null> {
  return parseShared(await invokeShell("offer_recent_photo"));
}
