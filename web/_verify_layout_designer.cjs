/* 首页布局设计器 · 验收脚本（file:// 直开，无服务依赖）
 * 1) 1440×900 截图 web/_layout_designer.png
 * 2) 初始坐标 = _layout_measure.json 实测值（1:1）
 * 3) 拖动「实时地图」+100,+40 → 导出 JSON 坐标同步
 * 4) 缩放「可见光视频」到 500×300 → 导出 JSON 宽高正确
 * 5) 重置 → 回到初始坐标
 * 6) 边界钳制 / 4px 吸附 / 锁定 / 网格 / CSS Grid / localStorage
 * 7) 全程无 JS 异常
 */
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
const { pathToFileURL } = require('url')

const ROOT = 'D:\\Desktop\\防爆机器人'
const EXE = path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium-1243', 'chrome-win64', 'chrome.exe')
const FILE = path.join(ROOT, 'web', 'layout-designer.html')
const MEASURE = path.join(ROOT, 'web', '_layout_measure.json')
const SHOT = path.join(ROOT, 'web', '_layout_designer.png')
const SHOT_EDIT = path.join(ROOT, 'web', '_layout_designer_edited.png')
const OUT = path.join(ROOT, 'web', '_layout_verify.json')

const checks = []
function check(name, ok, detail) {
  checks.push({ name, ok: !!ok, detail })
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (detail ? '  ' + JSON.stringify(detail) : ''))
}
const near = (a, b, tol = 0.01) => Math.abs(Number(a) - Number(b)) <= tol
const rectOf = (mods, id) => {
  const m = mods.find((x) => x.id === id)
  return m ? { x: m.x, y: m.y, w: m.w, h: m.h } : null
}

async function dragBy(page, locator, dxCanvas, dyCanvas, scale, midCheck) {
  const b = await locator.boundingBox()
  if (!b) throw new Error('no bounding box for drag target')
  const cx = b.x + b.width / 2
  const cy = b.y + b.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  const steps = 10
  for (let i = 1; i <= steps; i += 1) {
    await page.mouse.move(cx + (dxCanvas * scale * i) / steps, cy + (dyCanvas * scale * i) / steps)
    if (i === 1 && midCheck) await midCheck()
  }
  await page.mouse.up()
}

async function exportJson(page) {
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#btnExport'),
  ])
  const p = await dl.path()
  const text = fs.readFileSync(p, 'utf8')
  return { name: dl.suggestedFilename(), data: JSON.parse(text) }
}

async function main() {
  const measure = JSON.parse(fs.readFileSync(MEASURE, 'utf8'))
  const measured = measure.modules
  const browser = await chromium.launch({
    headless: true, executablePath: EXE,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox'],
  })
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 }, locale: 'zh-CN', deviceScaleFactor: 1, acceptDownloads: true,
  })
  const page = await ctx.newPage()
  page.setDefaultTimeout(20000)
  const errors = []
  const consoleErrors = []
  page.on('pageerror', (e) => errors.push(String(e && e.stack ? e.stack : e).slice(0, 400)))
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) })

  const result = { url: pathToFileURL(FILE).href, checks, errors, consoleErrors }
  try {
    await page.goto(pathToFileURL(FILE).href, { waitUntil: 'load' })
    await page.waitForFunction(() => window.__layoutDesignerReady === true, null, { timeout: 10000 })
    await page.waitForTimeout(400)

    const scale = await page.evaluate(() => window.layoutDesigner.getScale())
    result.scale = scale
    check('画布按窗口等比缩放（0<scale<=1）', scale > 0.5 && scale <= 1, { scale })

    /* ---------- 1. 初始 1:1 ---------- */
    const st0 = await page.evaluate(() => window.layoutDesigner.getState())
    const initMismatch = []
    for (const [id, mm] of Object.entries(measured)) {
      const got = rectOf(st0.modules, id)
      const want = mm.rect
      if (!got || !near(got.x, want.x) || !near(got.y, want.y) || !near(got.w, want.w) || !near(got.h, want.h)) {
        initMismatch.push({ id, got, want: { x: want.x, y: want.y, w: want.w, h: want.h } })
      }
    }
    check('初始 10 个模块坐标 = 首页实测值（1:1）', initMismatch.length === 0, initMismatch)
    check('模块数 = 10', st0.modules.length === 10, { count: st0.modules.length, chip: await page.textContent('#cCount') })

    // DOM 实际几何与状态一致（排除 transform 后）
    const domDrift = await page.evaluate((scale) => {
      const s = window.layoutDesigner.getState()
      return s.modules.map((m) => {
        const el = document.querySelector('.mod[data-id="' + m.id + '"]')
        const r = el.getBoundingClientRect()
        return { id: m.id, dx: +(r.width / scale - m.w).toFixed(2), dy: +(r.height / scale - m.h).toFixed(2) }
      }).filter((d) => Math.abs(d.dx) > 0.6 || Math.abs(d.dy) > 0.6)
    }, scale)
    check('DOM 渲染尺寸与布局状态一致', domDrift.length === 0, domDrift)

    await page.screenshot({ path: SHOT })
    check('截图 web/_layout_designer.png', fs.existsSync(SHOT) && fs.statSync(SHOT).size > 20000, { bytes: fs.statSync(SHOT).size })

    /* ---------- 2. 拖动实时地图 +100,+40 ---------- */
    let liveSeen = null
    const scaleBeforeDrag = await page.evaluate(() => window.layoutDesigner.getScale())
    await dragBy(page, page.locator('.mod[data-id="map"] .mod-head'), 100, 40, scale, async () => {
      liveSeen = await page.evaluate(() => {
        const el = document.getElementById('liveSize')
        return { on: el.classList.contains('on'), text: el.textContent.trim() }
      })
    })
    check('拖动中显示实时「宽×高」', !!(liveSeen && liveSeen.on && /×/.test(liveSeen.text)), liveSeen)
    const scaleAfterDrag = await page.evaluate(() => window.layoutDesigner.getScale())
    check('拖动过程中画布缩放保持稳定（工具栏不换行）', near(scaleBeforeDrag, scaleAfterDrag, 1e-9), { scaleBeforeDrag, scaleAfterDrag })

    const st1 = await page.evaluate(() => window.layoutDesigner.getState())
    const map1 = rectOf(st1.modules, 'map')
    // 410 + 100 = 510 不在 4px 网格上 → 吸附到 512；104 + 40 = 144 正好在网格上
    check('拖动 +100,+40 后实时地图吸附落点 = 512,144', near(map1.x, 512) && near(map1.y, 144), map1)
    check('拖动 +100 的位移符合 4px 吸附（510→512）', map1.x - 410 === 102 && map1.y - 104 === 40, { dx: map1.x - 410, dy: map1.y - 104 })

    const ex1 = await exportJson(page)
    const mapEx = rectOf(ex1.data.modules, 'map')
    check('导出 layout.json 文件名正确', ex1.name === 'layout.json', { name: ex1.name })
    check('导出 JSON 里实时地图坐标同步 = 512,144', near(mapEx.x, 512) && near(mapEx.y, 144), mapEx)
    check('导出 JSON 含 id/name/x/y/w/h', ex1.data.modules.every((m) => ['id', 'name', 'x', 'y', 'w', 'h'].every((k) => k in m)), { keys: Object.keys(ex1.data.modules[0]) })

    /* ---------- 3. 缩放可见光视频 → 500×300 ---------- */
    const vis0 = rectOf(st1.modules, 'visible')
    await dragBy(page, page.locator('.mod[data-id="visible"] .rs'), 500 - vis0.w, 300 - vis0.h, scale)
    const st2 = await page.evaluate(() => window.layoutDesigner.getState())
    const vis2 = rectOf(st2.modules, 'visible')
    check('缩放到 500×300 后 DOM 宽高正确', near(vis2.w, 500) && near(vis2.h, 300), vis2)

    const ex2 = await exportJson(page)
    const visEx = rectOf(ex2.data.modules, 'visible')
    const mapEx2 = rectOf(ex2.data.modules, 'map')
    check('导出 JSON 里可见光视频 = 500×300', near(visEx.w, 500) && near(visEx.h, 300), visEx)
    check('导出 JSON 里实时地图仍保持拖动后坐标', near(mapEx2.x, 512) && near(mapEx2.y, 144), mapEx2)
    await page.screenshot({ path: SHOT_EDIT })

    /* ---------- 4. 边界钳制 + 4px 吸附 ---------- */
    const vb = await page.locator('.mod[data-id="visible"] .mod-head').boundingBox()
    await page.mouse.move(vb.x + vb.width / 2, vb.y + vb.height / 2)
    await page.mouse.down()
    await page.mouse.move(6, 6, { steps: 12 })
    await page.mouse.up()
    const stEdge1 = await page.evaluate(() => window.layoutDesigner.getState())
    const vEdge1 = rectOf(stEdge1.modules, 'visible')
    check('不能拖出画布左上角（x=0,y=0）', near(vEdge1.x, 0) && near(vEdge1.y, 0), vEdge1)

    const vb2 = await page.locator('.mod[data-id="visible"] .mod-head').boundingBox()
    await page.mouse.move(vb2.x + 6, vb2.y + 6)
    await page.mouse.down()
    await page.mouse.move(1434, 894, { steps: 14 })
    await page.mouse.up()
    const stEdge2 = await page.evaluate(() => window.layoutDesigner.getState())
    const vEdge2 = rectOf(stEdge2.modules, 'visible')
    check('不能拖出画布右下角（贴边 940,600）', near(vEdge2.x, 1440 - 500) && near(vEdge2.y, 900 - 300), vEdge2)
    check('拖动后坐标仍在 4px 网格上', [vEdge2.x, vEdge2.y].every((n) => Math.abs(n / 4 - Math.round(n / 4)) < 1e-6), vEdge2)

    /* ---------- 5. 重置 ---------- */
    await page.click('#btnReset')
    await page.waitForTimeout(150)
    const st3 = await page.evaluate(() => window.layoutDesigner.getState())
    const resetMismatch = []
    for (const [id, mm] of Object.entries(measured)) {
      const got = rectOf(st3.modules, id)
      const want = mm.rect
      if (!got || !near(got.x, want.x) || !near(got.y, want.y) || !near(got.w, want.w) || !near(got.h, want.h)) {
        resetMismatch.push({ id, got, want: { x: want.x, y: want.y, w: want.w, h: want.h } })
      }
    }
    check('重置后回到初始实测坐标', resetMismatch.length === 0, resetMismatch)
    const savedAfterReset = await page.evaluate(() => localStorage.getItem('jc_layout_designer_v1'))
    check('重置后清掉本地存档', savedAfterReset === null, { saved: savedAfterReset })
    check('工具栏显示模块数 10', (await page.textContent('#cCount')) === '10', {})

    /* ---------- 6. 保存 / 读取 ---------- */
    await page.click('#btnSave')
    await page.waitForTimeout(100)
    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('jc_layout_designer_v1') || 'null'))
    check('保存到 localStorage（含 10 个模块）', !!saved && saved.modules.length === 10, { key: 'jc_layout_designer_v1', count: saved && saved.modules.length })

    // 改一下再刷新：应恢复保存值而不是默认值
    await dragBy(page, page.locator('.mod[data-id="points"] .mod-head'), -40, 0, scale)
    const pointsAfterDrag = rectOf((await page.evaluate(() => window.layoutDesigner.getState())).modules, 'points')
    await page.click('#btnSave')
    await page.reload({ waitUntil: 'load' })
    await page.waitForFunction(() => window.__layoutDesignerReady === true, null, { timeout: 10000 })
    await page.waitForTimeout(200)
    const stReload = await page.evaluate(() => window.layoutDesigner.getState())
    const pointsReload = rectOf(stReload.modules, 'points')
    check('刷新后从 localStorage 恢复（巡检点位 x=1060）', near(pointsReload.x, 1060) && near(pointsReload.x, pointsAfterDrag.x), { pointsReload, pointsAfterDrag })

    await page.evaluate(() => { localStorage.removeItem('jc_layout_designer_v1') })
    await page.reload({ waitUntil: 'load' })
    await page.waitForFunction(() => window.__layoutDesignerReady === true, null, { timeout: 10000 })
    await page.waitForTimeout(200)

    /* ---------- 7. 锁定 ---------- */
    await page.click('#btnLock')
    await page.waitForTimeout(80)
    const lockScale = await page.evaluate(() => window.layoutDesigner.getScale())
    const mapBefore = rectOf((await page.evaluate(() => window.layoutDesigner.getState())).modules, 'map')
    await dragBy(page, page.locator('.mod[data-id="map"] .mod-head'), 60, 60, lockScale)
    const mapLocked = rectOf((await page.evaluate(() => window.layoutDesigner.getState())).modules, 'map')
    check('锁定模块后拖不动', near(mapLocked.x, mapBefore.x) && near(mapLocked.y, mapBefore.y), { before: mapBefore, after: mapLocked })
    await page.click('#btnLock')

    /* ---------- 8. 网格开关 ---------- */
    await page.click('#btnGrid')
    check('显示网格开关生效', await page.evaluate(() => document.getElementById('gridLayer').classList.contains('on')), {})
    await page.click('#btnGrid')

    /* ---------- 9. CSS Grid 导出 ---------- */
    await page.click('#btnCopy')
    await page.waitForTimeout(200)
    const cssState = await page.evaluate(() => {
      const ta = document.getElementById('cssText')
      return {
        open: document.getElementById('cssMask').classList.contains('on'),
        css: ta.value,
        selected: ta.selectionStart === 0 && ta.selectionEnd === ta.value.length,
      }
    })
    const colMatch = cssState.css.match(/grid-template-columns:\s*([^;]+);/)
    const rowMatch = cssState.css.match(/grid-template-rows:\s*([^;]+);/)
    const sum = (s) => s.split(/\s+/).filter(Boolean).reduce((n, v) => n + parseFloat(v), 0)
    const colSum = colMatch ? sum(colMatch[1]) : -1
    const rowSum = rowMatch ? sum(rowMatch[1]) : -1
    check('CSS Grid 弹窗打开且已全选', cssState.open && cssState.selected, { open: cssState.open })
    check('CSS 列宽合计=1440 / 行高合计=900', near(colSum, 1440, 0.5) && near(rowSum, 900, 0.5), { colSum, rowSum })
    check('CSS 含每个模块的 grid-column/grid-row', (cssState.css.match(/grid-column:/g) || []).length === 10 && (cssState.css.match(/grid-row:/g) || []).length === 10, {})
    check('CSS 含坐标表与绝对定位版本', cssState.css.includes('坐标表') && cssState.css.includes('.abs-map'), {})
    result.cssPreview = cssState.css.split('\n').slice(0, 26).join('\n')
    await page.click('#cssClose')

    /* ---------- 10. 收尾 ---------- */
    await page.click('#btnReset')
    await page.waitForTimeout(2700)   // 等 toast 消失，截图干净
    await page.screenshot({ path: SHOT })
    result.finalState = await page.evaluate(() => window.layoutDesigner.getState())
    check('无 JS 异常（pageerror 0）', errors.length === 0, errors)
    check('无 console.error', consoleErrors.length === 0, consoleErrors)
  } finally {
    await browser.close()
  }

  result.pass = checks.filter((c) => c.ok).length
  result.fail = checks.filter((c) => !c.ok).length
  fs.writeFileSync(OUT, JSON.stringify(result, null, 2), 'utf8')
  console.log('\n' + result.pass + ' passed, ' + result.fail + ' failed -> ' + OUT)
  if (result.fail) process.exitCode = 1
}

main().catch((e) => { console.error('FAIL:', (e && e.stack) || e); process.exit(1) })
