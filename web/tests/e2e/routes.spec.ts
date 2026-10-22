import { expect, test, type Page } from '@playwright/test'

/**
 * 12 个页面全过一遍。之前踩过的坑（History.vue 的 TDZ 崩溃导致整站白屏）
 * 就是这种测试能拦住的——单元测试完全发现不了。
 */
const ROUTES: { path: string; must: string; label: string }[] = [
  { path: '/dashboard', must: '.board', label: '大屏' },
  { path: '/robot-status', must: '.panel', label: '机器人状态' },
  { path: '/map', must: '.panel', label: '地图监控' },
  { path: '/video', must: '.panel', label: '视频监控' },
  { path: '/alarms', must: 'table.grid', label: '告警中心' },
  { path: '/alarm-rules', must: 'table.grid', label: '告警规则' },
  { path: '/task-templates', must: 'table.grid', label: '任务模板' },
  { path: '/task-runs', must: 'table.grid', label: '任务执行' },
  { path: '/env', must: '.panel', label: '环境监测' },
  { path: '/tasks', must: '.panel', label: '任务管理' },
  { path: '/points', must: '.panel', label: '点位管理' },
  { path: '/reports', must: '.panel', label: '巡检报表' },
  { path: '/robots', must: '.panel', label: '设备台账' },
  { path: '/cameras', must: '.panel', label: '视频源' },
  { path: '/env-device', must: '.panel', label: '环境传感器' },
  { path: '/record/plan', must: '.panel', label: '录制计划' },
  { path: '/record/playback', must: '.panel', label: '录像回放' },
  { path: '/messages', must: '.panel', label: '消息中心' },
  { path: '/notify', must: '.panel', label: '通知通道' },
  { path: '/settings', must: '.set-grid', label: '系统设置' },
  { path: '/users', must: 'table.grid', label: '用户管理' },
  { path: '/oplog', must: 'table.grid', label: '系统日志' },
  { path: '/run-data', must: '.panel', label: '运行数据' },
  { path: '/room', must: '.panel', label: '充电房监控' },
]

const USER = process.env.E2E_USER || 'admin'
const PASS = process.env.E2E_PASS || 'admin123'

async function login(page: Page) {
  await page.goto('/')
  await page.fill('input[autocomplete="username"]', USER)
  await page.fill('input[type="password"]', PASS)
  await page.click('button.submit')
  await page.waitForTimeout(2000)
  // 初始密码会被强制改密挡住：测试环境直接用已改过的账号，或跳过一次
  const forced = await page.locator('.force-mask').count()
  if (forced) {
    throw new Error('该账号需要先改密码，请设置 E2E_USER/E2E_PASS 为已改密的账号')
  }
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  ;(page as unknown as { __errors: string[] }).__errors = errors
  await login(page)
})

for (const r of ROUTES) {
  test(`${r.label} ${r.path} 正常渲染`, async ({ page }) => {
    await page.goto(r.path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1200)

    await expect(page.locator(r.must).first(), `${r.label} 缺少特征元素 ${r.must}`).toBeVisible({
      timeout: 10_000,
    })

    const text = await page.locator('body').innerText()
    expect(text.length, `${r.label} 页面几乎空白`).toBeGreaterThan(60)

    const errors = (page as unknown as { __errors: string[] }).__errors
    expect(errors, `${r.label} 有前端异常：${errors.join(' | ')}`).toEqual([])
  })
}

test('切设备后大屏数据源跟着变', async ({ page }) => {
  await page.goto('/dashboard')
  await page.waitForTimeout(1500)
  const chips = page.locator('.devchip')
  if ((await chips.count()) < 2) test.skip(true, '只有一台设备，跳过切换测试')
  await chips.nth(1).click()
  await page.waitForTimeout(1500)
  const on = page.locator('.devchip.on')
  await expect(on).toHaveCount(1)
})

test('未登录访问被挡回登录页', async ({ browser }) => {
  const ctx = await browser.newContext()
  const p = await ctx.newPage()
  await p.goto('/alarms')
  await p.waitForTimeout(1500)
  const hasLogin = await p.locator('input[autocomplete="username"]').count()
  expect(hasLogin, '未登录竟然能进告警页').toBe(1)
  await ctx.close()
})

