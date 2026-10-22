import { chromium } from 'playwright';
const out = process.env.HOME + '/ptshots';
const browser = await chromium.launch({ executablePath: process.env.HOME + '/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const errors=[], failed=[], consoleErrs=[];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type()==='error') consoleErrs.push(m.text().slice(0,300)); });
page.on('requestfailed', r => failed.push(r.url()+' :: '+(r.failure()?.errorText||'')));
page.on('response', r => { if (r.status()>=400) failed.push('HTTP '+r.status()+' '+r.url()); });
await page.goto('http://127.0.0.1:5173/login', { waitUntil:'networkidle' });
const inputs = await page.locator('input').all();
await inputs[0].fill('admin'); await inputs[1].fill('admin123');
await page.locator('button').filter({ hasText:/登录|登 录/ }).first().click().catch(()=>{});
await page.waitForTimeout(2500);
const paths = ['/points','/task-calendar','/alarms','/ai-results','/keys','/alarm-rules','/history/tasks','/history/alarms','/reports','/run-data','/robots','/cameras','/env-device','/record/plan','/record/playback','/messages','/users','/settings','/notify','/oplog'];
for (const p of paths) {
  try { await page.goto('http://127.0.0.1:5173'+p,{waitUntil:'networkidle',timeout:15000}); await page.waitForTimeout(1000);
    await page.screenshot({path: out+'/'+p.replaceAll('/','_')+'.png'});
    console.log('### '+p+'\n'+(await page.locator('body').innerText()).replace(/\n{2,}/g,'\n').slice(0,900)+'\n');
  } catch(e){ console.log('### '+p+' FAILED '+e.message.slice(0,150)); }
}
console.log('PAGEERRORS', JSON.stringify([...new Set(errors)].slice(0,20)));
console.log('CONSOLE', JSON.stringify([...new Set(consoleErrs)].slice(0,30)));
console.log('FAILED', JSON.stringify([...new Set(failed)].slice(0,50)));
await browser.close();
