// @vitest-environment node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { expect, it } from "vitest";
import { portraits, portraitSvg } from "./gen-agent-portraits";

it.each(portraits)("keeps $folder's starter picture in step with its recipe", async (portrait) => {
  const source = resolve(
    fileURLToPath(
      new URL("../../backend/app/core/catalog/agent_templates/general/", import.meta.url),
    ),
    portrait.folder,
    "avatar.png",
  );
  const actual = await readFile(source);
  const expected = await sharp(Buffer.from(portraitSvg(portrait)))
    .png()
    .toBuffer();
  expect(actual).toEqual(expected);
  const metadata = await sharp(actual).metadata();
  expect(metadata).toMatchObject({ width: 256, height: 256, hasAlpha: true });
});
