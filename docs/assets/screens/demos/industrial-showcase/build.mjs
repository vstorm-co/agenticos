import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root=dirname(fileURLToPath(import.meta.url));
const sans=readFileSync(join(root,'fonts/inter-latin.woff2')).toString('base64');
const mono=readFileSync(join(root,'fonts/geist-mono-latin.woff2')).toString('base64');
const css=readFileSync(join(root,'shared.css'),'utf8').replace('{{SANS}}',sans).replace('{{MONO}}',mono);
for(const name of ['revenue-pulse','northline-operations','motor-atlas']){
 const html=readFileSync(join(root,`${name}.html`),'utf8').replace('{{CSS}}',css).replace('{{MAP}}',readFileSync(join(root,'supply-map.svg'),'utf8'));
 writeFileSync(join(root,'..',`${name}.html`),html);
 console.log(`Built ${name}: ${Buffer.byteLength(html)} bytes`);
}
