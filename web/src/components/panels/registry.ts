/**
 * 面板注册表：能力 → 组件。
 *
 * 首页不再写死"可见光/热红外"两块，而是遍历 capabilities 找对应面板。
 * 新增一种外设（比如粉尘仪）：后端加 kind → 出现 env.read.dust →
 * 前端已有 EnvPanel 直接渲染，主页面零改动。
 */
export type PanelKey = 'video.live' | 'video.thermal' | 'env' | 'ptz' | 'posture' | 'audio'

export interface PanelDef {
  key: PanelKey
  match: string[]
  title: string
  once?: boolean
}

export const PANELS: PanelDef[] = [
  { key: 'video.live', match: ['video.live'], title: '可见光视频', once: true },
  { key: 'video.thermal', match: ['video.thermal'], title: '热红外视频', once: true },
  { key: 'env', match: ['env.read'], title: '环境数据', once: true },
  { key: 'ptz', match: ['ptz.move'], title: '云台控制', once: true },
  { key: 'posture', match: ['posture.'], title: '车体控制', once: true },
  { key: 'audio', match: ['audio.'], title: '语音喊话', once: true },
]

export function panelsFor(capabilities: string[]): PanelDef[] {
  return PANELS.filter((p) => p.match.some((m) => capabilities.some((c) => c.startsWith(m))))
}

export function has(capabilities: string[], cap: string): boolean {
  return capabilities.some((c) => c === cap || c.startsWith(cap + '.'))
}
