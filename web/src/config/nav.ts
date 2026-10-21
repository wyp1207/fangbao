import type { RouteRecordName } from 'vue-router'

export interface NavItem {
  name: string
  label: string
  /** true = 有真实数据；false = 进「未接入说明页」 */
  real?: boolean
}

export interface NavGroup {
  key: string
  label: string
  route?: string
  items?: NavItem[]
}

/**
 * 菜单树（豆包 + GLM 两个评审结论合并后定稿，2026-10-21）
 * - 砍掉：设备管理、录像管理、人脸识别、开发中心、充电房监控、任务库、地图设置
 * - 保留占位（不放假数据）：视频、环境、任务日历、运行数据、系统日志
 */
export const NAV: NavGroup[] = [
  { key: 'home', label: '首页', route: 'dashboard' },
  {
    key: 'monitor', label: '实时监控',
    items: [
      { name: 'robot-status', label: '机器人状态', real: true },
      { name: 'map', label: '地图监控', real: true },
      { name: 'video', label: '视频监控', real: true },
      { name: 'room', label: '充电房监控', real: true },
      { name: 'env', label: '环境监测' },
    ],
  },
  {
    key: 'patrol', label: '巡检管理',
    items: [
      { name: 'tasks', label: '任务管理', real: true },
      { name: 'points', label: '巡检点位', real: true },
      { name: 'task-calendar', label: '任务日历' },
    ],
  },
  {
    key: 'alarm', label: '告警中心',
    items: [
      { name: 'alarms', label: '告警记录', real: true },
      { name: 'alarm-rules', label: '告警规则', real: true },
    ],
  },
  {
    key: 'data', label: '数据查询',
    items: [
      { name: 'history-tasks', label: '任务数据', real: true },
      { name: 'history-alarms', label: '告警数据', real: true },
      { name: 'run-data', label: '运行数据' },
          { name: 'reports', label: '巡检报表' },
    ],
  },
  {
    key: 'device', label: '设备管理',
    items: [
      { name: 'robots', label: '机器人', real: true },
      { name: 'cameras', label: '摄像头', real: true },
      { name: 'env-device', label: '环境传感器' },
    ],
  },
  {
    key: 'record', label: '录像管理',
    items: [
      { name: 'record-plan', label: '录像计划' },
      { name: 'record-playback', label: '录像回放' },
    ],
  },
  {
    key: 'system', label: '系统管理',
    items: [
      { name: 'users', label: '用户管理', real: true },
      { name: 'settings', label: '系统设置', real: true },
      { name: 'notify', label: '告警通知' },
          { name: 'oplog', label: '系统日志' },
    ],
  },
]

export function isActive(group: NavGroup, current: RouteRecordName | null | undefined): boolean {
  if (group.route) return current === group.route
  return !!group.items?.some((i) => i.name === current)
}
