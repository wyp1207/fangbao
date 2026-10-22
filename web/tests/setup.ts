// jsdom 缺少的浏览器 API：组件挂载时会用到，不补会直接抛错
import { vi } from 'vitest'

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO

if (!window.matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

if (!window.requestAnimationFrame) {
  window.requestAnimationFrame = ((cb: FrameRequestCallback) =>
    setTimeout(() => cb(performance.now()), 0)) as typeof window.requestAnimationFrame
}
