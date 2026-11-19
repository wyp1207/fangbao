/* 首页布局实测：1440x900 下 getBoundingClientRect（相对视口 = 画布坐标）
 * 输出 _layout_measure.json + 首页截图 web/_home_baseline.png
 */
const { chromium } = require('playwright')
const path = require('path')
const fs = require('fs')

const ROOT = 'D:\\Desktop\\防爆机器人'
const BASE = 'http://127.0.0.1:5173'
const EXE = path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1243', 'chrome-win64', 'chrome.exe')
const OUT = path.join(ROOT, 'web', '_layout_measure.json')
const SHOT = path.join(ROOT, 'web', '_home_baseline.png')

const MODULES = [
  ['header', '顶栏', 'header.hdr'],
  ['footer', '底栏', 'footer.footbar'],
  ['visible', '可见光视频', 'aside.col.left > .t-panel:nth-of-type(1)'],
  ['thermal', '热红外视频', 'aside.col.left > .t-panel:nth-of-type(2)'],
  ['control', '实时控制', 'aside.col.left > .t-panel:nth-of-type(3)'],
  ['map', '实时地图', 'main.col.center > .t-panel'],
  ['messages', '实时消息', 'main.col.center > section.rt'],
  ['alarm', '告警统计', 'aside.col.right > .t-panel:nth-of-type(1)'],
  ['env', '环境数据', 'aside.col.right > .t-panel:nth-of-type(2)'],
  ['points', '巡检点位', 'aside.col.right > .t-panel:nth-of-type(3)'],
]

async function main() {
  const browser = await chromium.launch({
    headless: true, executablePath: EXE,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
  })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN', deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  page.setDefaultTimeout(40000)
  const errs = []
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 300)))
  const result = {}
  try {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' })
    await page.locator('.login-page input:not([type="password"])').first().fill('admin')
    await page.locator('.login-page input[type="password"]').fill('admin123')
    await page.locator('button.submit').click()
    await page.waitForFunction(() => location.pathname.includes('/dashboard'), null, { timeout: 45000 })
    await page.waitForSelector('aside.col.right > .t-panel', { state: 'visible', timeout: 30000 })
    await page.waitForTimeout(6000)
    await page.screenshot({ path: SHOT })

    const data = await page.evaluate((MODULES) => {
      const r = (el) => {
        const b = el.getBoundingClientRect()
        return {
          x: +b.left.toFixed(2), y: +b.top.toFixed(2),
          w: +b.width.toFixed(2), h: +b.height.toFixed(2),
          x2: +b.right.toFixed(2), y2: +b.bottom.toFixed(2),
        }
      }
      const out = {}
      for (const [id, name, sel] of MODULES) {
        const el = document.querySelector(sel)
        out[id] = { name, sel, found: !!el, rect: el ? r(el) : null }
      }
      const q = (s) => document.querySelector(s)
      return {
        viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio },
        title: q('.board-title h1')?.textContent?.trim() || '',
        modules: out,
        doc: { scrollW: document.documentElement.scrollWidth, scrollH: document.documentElement.scrollHeight, clientW: document.documentElement.clientWidth, clientH: document.documentElement.clientHeight },
        bodyH: q('.body') ? r(q('.body')) : null,
        subbarH: q('.subbar') ? r(q('.subbar')) : null,
      }
    }, MODULES)
    Object.assign(result, data)
  } finally {
    await browser.close()
  }
  result.errors = errs
  fs.writeFileSync(OUT, JSON.stringify(result, null, 2), 'utf8')
  console.log(JSON.stringify(result, null, 2))
}
main().catch((e) => { console.error('FAIL:', (e && e.stack) || e); process.exit(1) })
