/** Render starter-agent pictures without changing the application's brand mark. */
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import { blobatar, type BlobatarOptions } from "blobatar";
import sharp from "sharp";
import { AVATAR_TRAITS } from "../src/lib/avatar-policy";

export const portraits: { folder: string; seed: string; options: BlobatarOptions }[] = [
  {
    folder: "agenticos",
    seed: "agenticos",
    options: { hue: 265, tone: 0.1, palette: { head: "#c4b5fd", eye: "#252039" } },
  },
];
export function portraitSvg(portrait: (typeof portraits)[number]): string {
  return blobatar(portrait.seed, {
    size: 256,
    background: false,
    traits: AVATAR_TRAITS,
    ...portrait.options,
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for (const portrait of portraits) {
    const path = resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../../backend/app/core/catalog/agent_templates/general",
      portrait.folder,
      "avatar.png",
    );
    await sharp(Buffer.from(portraitSvg(portrait)))
      .png()
      .toFile(path);
    console.log(path);
  }
}
