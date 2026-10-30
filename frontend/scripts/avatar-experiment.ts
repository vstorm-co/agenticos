/** Offline comparison of Blobatar 2.7 defaults against console portrait policies. */
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { blobatar, type BlobatarOptions } from "blobatar";
import sharp from "sharp";
import { portraitSvg, portraits } from "./gen-agent-portraits";
import { AVATAR_TRAITS, portraitHue } from "../src/lib/avatar-policy";

const destination = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../docs/plans/avatar-experiment-2026-10-28",
);
const seeds = [
  "agenticos",
  "architect",
  "browser_agent",
  "background-browse-demo-1792144884",
  "supplier-invoice-policy-helper",
  "claude-code-like",
  "support-copilot",
  "test",
];
const variants: { name: string; options: BlobatarOptions }[] = [
  { name: "Library defaults", options: {} },
  { name: "Silhouette limits only", options: { traits: { shape: [0.1, 0.34, 0.54] } } },
  { name: "Balanced portraits (selected)", options: { traits: AVATAR_TRAITS } },
];
const width = 1440;
const height = 1340;
const chunks = [
  `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#eeeef0"/><style>text{font-family:Arial,sans-serif}</style><text x="24" y="34" font-size="22" fill="#202024">AgenticOS · Blobatar 2.7 · 24 / 36 / 56 px</text>`,
];
for (const [column, variant] of variants.entries()) {
  const x = column * 480;
  chunks.push(`<text x="${x + 24}" y="70" font-size="17" fill="#202024">${variant.name}</text>`);
  for (const [row, seed] of seeds.entries()) {
    const y = 90 + row * 130;
    chunks.push(`<text x="${x + 24}" y="${y + 14}" font-size="12" fill="#555560">${seed}</text>`);
    for (const [theme, bg] of ["#fafafa", "#202124"].entries()) {
      const left = x + 20 + theme * 224;
      chunks.push(`<rect x="${left}" y="${y + 25}" width="216" height="88" rx="10" fill="${bg}"/>`);
      for (const [index, size] of [24, 36, 56].entries()) {
        const drawing = blobatar(seed, {
          ...variant.options,
          ...(column === 2 ? { hue: portraitHue(seed) } : {}),
          size,
          background: false,
        });
        chunks.push(
          drawing.replace(
            "<svg ",
            `<svg x="${left + 18 + index * 60}" y="${y + 25 + (88 - size) / 2}" `,
          ),
        );
      }
    }
  }
}
chunks.push(
  '<text x="24" y="1170" font-size="18" fill="#202024">Starter agent portraits · violet AgenticOS / blue Architect · 24 / 36 / 56 px</text>',
);
for (const [index, portrait] of portraits.entries()) {
  const left = 24 + index * 480;
  for (const [theme, fill] of ["#fafafa", "#202124"].entries()) {
    const x = left + theme * 220;
    chunks.push(`<rect x="${x}" y="1190" width="208" height="100" rx="10" fill="${fill}"/>`);
    for (const [i, size] of [24, 36, 56].entries()) {
      chunks.push(
        portraitSvg(portrait).replace(
          /width="256" height="256"/,
          `x="${x + 12 + i * 60}" y="${1240 - size / 2}" width="${size}" height="${size}"`,
        ),
      );
    }
  }
}
chunks.push("</svg>");
await mkdir(destination, { recursive: true });
const sheet = chunks.join("");
await writeFile(resolve(destination, "comparison.svg"), sheet + "\n");
await sharp(Buffer.from(sheet)).png().toFile(resolve(destination, "comparison.png"));
console.log(destination);
