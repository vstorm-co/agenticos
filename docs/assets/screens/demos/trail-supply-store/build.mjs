import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
for (const [template, name] of [
  ["store.html", "trail-supply"],
  ["kit.html", "trail-supply-kit"],
]) {
  let html = await readFile(new URL(`./${template}`, import.meta.url), "utf8");
  for (const image of ["backpack", "basket", "bottle"]) {
    const bytes = await readFile(new URL(`./assets/${image}.webp`, import.meta.url));
    html = html.replaceAll(`{{${image}}}`, `data:image/webp;base64,${bytes.toString("base64")}`);
  }
  const output = new URL(`../${name}.html`, import.meta.url);
  await writeFile(output, html);
  process.stdout.write(`Built ${fileURLToPath(output)} (${Buffer.byteLength(html)} bytes)\n`);
}
