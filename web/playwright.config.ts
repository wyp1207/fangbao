import { defineConfig } from '@playwright/test'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/**
 * 端到端冒烟：12 个路由逐个打开，要求
 *   1) 没有 pageerror（组件崩溃）
 *   2) 页面不是空白（正文长度 > 阈值）
 *   3) 关键元素存在（每页一个特征选择器）
 *
 * 需要先起 dev：后端 8000 + vite 5173（或部署好的 8099）。
 *   npm run test:e2e
 *   BASE_URL=http://192.168.8.40:8099 npm run test:e2e
 */
function chromiumPath(): string | undefined {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(), 'AppData', 'Local', 'ms-playwright')
  if (!existsSync(root)) return undefined
  const dirs = readdirSync(root).filter((d) => d.startsWith('chromium-'))
  for (const d of dirs) {
    const exe = join(root, d, 'chrome-win64', 'chrome.exe')
    if (existsSync(exe)) return exe
  }
  return undefined
}

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:5173',
    viewport: { width: 1440, height: 900 },
    launchOptions: { executablePath: chromiumPath() },
    trace: 'off',
  },
})
