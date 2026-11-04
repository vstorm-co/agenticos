import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root=dirname(fileURLToPath(import.meta.url));
const require=createRequire(join(root,'../../../../../frontend/package.json'));
const {chromium,expect}=require('@playwright/test');
const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL??'chrome'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function open(name){await page.goto(pathToFileURL(join(root,'..',name+'.html')).href);await page.locator('h1').waitFor();}
 await open('revenue-pulse');await expect(page.locator('.metric-value').first()).toHaveText('€1,240,000');await expect(page.locator('.metric-value').nth(1)).toHaveText('100.8%');
 await page.getByRole('button',{name:'Previous 6 months'}).click();await expect(page.locator('.metric-value').first()).toHaveText('€925,000');await expect(page.locator('.metric-note').nth(1)).toHaveText('€30,000 below period target');await expect(page.locator('#finding')).toContainText('3.3% below its demo target');
 await page.getByLabel('Region',{exact:true}).selectOption('eu');await expect(page.locator('.metric-value').first()).toHaveText('€573,500');await expect(page.locator('.metric-value').nth(2)).toHaveText('€799,800');
 await page.locator('[data-person="0"]').click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'Close',exact:true}).click();
 await open('northline-operations');await expect(page.locator('.metric-value').first()).toHaveText('486');await expect(page.locator('.metric-value').nth(1)).toHaveText('3');
 await page.getByRole('button',{name:'Simulate +24h delay'}).click();await expect(page.locator('.metric-value').nth(1)).toHaveText('4');
 await page.getByRole('button',{name:'Inbound deliveries',exact:true}).click();await page.locator('#delivery-filter').selectOption('risk');await expect(page.locator('#shipments tr')).toHaveCount(4);
 await page.locator('#shipments [data-review="NL-480"]').click();await expect(page.locator('#shipment-body')).toContainText('03 Nov 10:00');await page.getByRole('button',{name:'Close review'}).click();
 await page.getByRole('button',{name:'Reset scenario'}).click();await expect(page.locator('#shipments tr')).toHaveCount(3);await page.locator('#delivery-filter').selectOption('all');await expect(page.locator('#shipments tr')).toHaveCount(8);
 await open('motor-atlas');await page.locator('#part-buttons button').nth(3).click();await expect(page.locator('#part-name')).toHaveText('Drive-end bearing');
 const exploded=await page.locator('#assembly').innerHTML();await page.getByRole('button',{name:'Assembled',exact:true}).click();await expect(page.locator('#separation')).toHaveValue('0');assert.notEqual(await page.locator('#assembly').innerHTML(),exploded);
 await page.getByRole('button',{name:'Exploded view',exact:true}).click();await expect(page.locator('#separation')).toHaveValue('86');await page.getByRole('button',{name:'Open component review'}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'Close review'}).click();
 for(const width of[390,320]){await page.setViewportSize({width,height:900});for(const name of['revenue-pulse','northline-operations','motor-atlas']){await open(name);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${name}: ${width}px overflow`);await expect(page.getByRole('heading',{level:1})).toBeVisible()}}
 assert.deepEqual(errors,[]);console.log('Passed revenue arithmetic/filters, shipment scenario/filter/review, assembly selection/separation, dialogs and six mobile layouts.');
}finally{await browser.close();}
