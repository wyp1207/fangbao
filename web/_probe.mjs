import { chromium } from 'playwright';
const out = process.env.HOME + '/ptshots';
const browser = await chromium.launch({ executablePath: process.env.HOME + '/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const errors = [], failed = [], consoleErrs = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type()==='error') consoleErrs.push(m.text().slice(0,300)); });
page.on('requestfailed', r => failed.push(r.url()+' :: '+(r.failure()?.errorText||'')));
page.on('response', r => { if (r.status()>=400) failed.push('HTTP '+r.status()+' '+r.url()); });

await page.goto('http://127.0.0.1:5173/login', { waitUntil: 'networkidle' });
await page.fill('input[type=text], input[name=username], input', 'admin').catch(()=>{});
const inputs = await page.locator('input').all();
if (inputs.length >= 2) { await inputs[0].fill('admin'); await inputs[1].fill('admin123'); }
await page.screenshot({ path: out+'/00-login.png', fullPage:true });
await page.locator('button').filter({ hasText: /登录|登 录/ }).first().click().catch(async()=>{ await page.keyboard.press('Enter'); });
await page.waitForTimeout(2500);
await page.screenshot({ path: out+'/01-after-login.png', fullPage:true });

const paths = ['/dashboard','/robot-status','/map','/video','/room','/env','/tasks','/inspection','/work-orders','/task-runs','/task-templates','/points','/task-calendar','/alarms','/ai-results','/keys','/alarm-rules','/history/tasks','/history/alarms','/reports','/run-data','/robots','/cameras','/env-device','/record/plan','/record/playback','/messages','/users','/settings','/notify','/oplog'];
for (const p of paths) {
  try {
    await page.goto('http://127.0.0.1:5173'+p, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1200);
    const name = p.replaceAll('/','_');
    await page.screenshot({ path: out+'/'+name+'.png', fullPage:false });
    const txt = (await page.locator('body').innerText()).replace(/\n{2,}/g,'\n').slice(0,600);
    console.log('### '+p+'\n'+txt+'\n');
  } catch(e) { console.log('### '+p+' FAILED '+e.message.slice(0,200)); }
}
console.log('PAGEERRORS', JSON.stringify(errors.slice(0,20)));
console.log('CONSOLE', JSON.stringify(consoleErrs.slice(0,30)));
console.log('FAILED', JSON.stringify([...new Set(failed)].slice(0,40)));
await browser.close();
