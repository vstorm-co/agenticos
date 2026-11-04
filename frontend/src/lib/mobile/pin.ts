/**
 * An agent pinned to the phone's home screen (#2097,
 * `mobile/src-tauri/src/pin.rs`): its face drawn as a launcher icon here, where
 * the face is known, and handed to the app with the agent's name.
 */

import { blobatarUri } from "blobatar/uri";

import { avatarHue } from "@/lib/avatar-color";
import { invokeShell, ShellError } from "@/lib/desktop/shell";

/** An adaptive icon's 108dp at the density launchers ask for. */
export const ICON_SIZE = 432;
/** What a launcher's mask leaves of an adaptive icon: its middle two thirds. */
const SAFE_SIDE = (ICON_SIZE * 2) / 3;

export interface PinnableAgent {
  id: string;
  name: string;
  slug: string;
  hasAvatar: boolean;
  colorSlot: number | null;
}

function load(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    // i18n-exempt: a developer's message, logged by reportShellFailure
    image.onerror = () => reject(new Error(`could not draw ${src.slice(0, 40)}`));
    image.src = src;
  });
}

/**
 * The agent's face as a PNG an adaptive launcher icon is made of, base64. An
 * uploaded picture fills the square; a generated face sits in the middle on
 * its own colour, out of reach of the launcher's mask.
 */
export async function agentIcon(agent: PinnableAgent): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = ICON_SIZE;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no canvas to draw the agent's face on");
  if (agent.hasAvatar) {
    const response = await fetch(`/api/agents/${agent.id}/avatar`);
    // i18n-exempt: a developer's message, logged by reportShellFailure
    if (!response.ok) throw new Error(`the agent's picture answered ${response.status}`);
    const picture = await load(URL.createObjectURL(await response.blob()));
    const side = Math.min(picture.width, picture.height);
    context.drawImage(
      picture,
      (picture.width - side) / 2,
      (picture.height - side) / 2,
      side,
      side,
      0,
      0,
      ICON_SIZE,
      ICON_SIZE,
    );
    URL.revokeObjectURL(picture.src);
  } else {
    const hue = avatarHue(agent.colorSlot);
    const backdrop = await load(blobatarUri(agent.slug, { hue, background: "square" }));
    context.drawImage(backdrop, 0, 0, ICON_SIZE, ICON_SIZE);
    const face = await load(blobatarUri(agent.slug, { hue, background: false }));
    const inset = (ICON_SIZE - SAFE_SIDE) / 2;
    context.drawImage(face, inset, inset, SAFE_SIDE, SAFE_SIDE);
  }
  return canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, "");
}

/**
 * Ask the launcher to place the agent on the home screen. Resolves to whether
 * it could: one that cannot pin has the agent in the app icon's long-press
 * list instead.
 */
export async function pinToHomeScreen(agent: PinnableAgent): Promise<boolean> {
  const icon = await agentIcon(agent);
  const answer = await invokeShell("pin_shortcut", {
    shortcut: { id: agent.id, name: agent.name, icon },
  });
  if (typeof answer === "object" && answer !== null && "pinned" in answer) {
    if (typeof answer.pinned === "boolean") return answer.pinned;
  }
  throw new ShellError("malformed", "a pinned shortcut");
}
