import { chromium } from 'playwright';
const out = process.env.HOME + '/ptshots';
const browser = await chromium.launch({ executablePath: process.env.HOME + '/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const fails=[]; page.on('response', r=>{if(r.status()>=400) fails.push(r.status()+' '+r.url())});
await page.goto('http://127.0.0.1:5173/login',{waitUntil:'networkidle'});
const ins=await page.locator('input').all(); await ins[0].fill('admin'); await ins[1].fill('admin123');
await page.locator('button').filter({hasText:/登录|登 录/}).first().click().catch(()=>{});
await page.waitForTimeout(2000);
for (const p of ['/m/task/1','/reports/print','/dashboard']) {
  await page.goto('http://127.0.0.1:5173'+p,{waitUntil:'networkidle',timeout:15000}); await page.waitForTimeout(1500);
  await page.screenshot({path: out+'/x'+p.replaceAll('/','_')+'.png', fullPage:true});
  console.log('### '+p+'\n'+(await page.locator('body').innerText()).slice(0,700)+'\n');
}
// click AI result 查看 and capture popup
await page.goto('http://127.0.0.1:5173/ai-results',{waitUntil:'networkidle'}); await page.waitForTimeout(1200);
const [pop] = await Promise.all([ page.waitForEvent('popup',{timeout:4000}).catch(()=>null), page.locator('a,button').filter({hasText:'查看'}).first().click().catch(()=>{}) ]);
if (pop) { await pop.waitForLoadState().catch(()=>{}); await pop.screenshot({path: out+'/ai-original.png'}).catch(()=>{}); console.log('POPUP URL', pop.url()); await pop.close(); } else { console.log('no popup; checking img'); await page.screenshot({path:out+'/ai-clicked.png'}); }
console.log('FAILS', JSON.stringify([...new Set(fails)].slice(0,30)));
await browser.close();
