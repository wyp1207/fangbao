import { request } from './client'

export type Role = 'admin' | 'operator' | 'viewer'

export interface User {
  id: number
  username: string
  role: Role
}

export interface StatusSnapshot {
  status: { status?: string }
  info: {
    battery?: number
    driver_port?: boolean
    charge?: boolean
    slam_type?: string
    info?: { version?: string; code_name?: string; port?: number }
  }
  galileo: Record<string, number | string | null>
  pose: { x?: number; y?: number; angle_deg?: number; theta_rad?: number }
  recv_ts: number
  age_s: number
  online: boolean
  consecutive_failures: number
  last_error: string | null
  poll_count: number
}

export interface UserRow {
  id: number
  username: string
  role: 'admin' | 'operator' | 'viewer'
  is_active: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface RobotRow {
  id: number
  name: string
  ip: string
  port: number
  mode: string
  version: string | null
  slam_type: string | null
  last_seen: string | null
}

export interface MapMeta {
  name: string
  resolution: number
  origin: [number, number, number]
  width?: number
  height?: number
  md5sum?: string
  map_type?: string
  levels?: number[]
  slam_type?: string
}

export interface NavPoint {
  x: number
  y: number
  theta_rad: number
  name: string
  error_x: number
  error_y: number
  direction: string
}

export interface AlarmItem {
  id: number
  metric: string
  level: 'warn' | 'critical'
  message: string
  value: unknown
  started_at: string
  acked_at: string | null
  acked_by: string | null
}

export const api = {
  login: (username: string, password: string) =>
    request<{ user: User; csrf_token: string }>('/auth/login', {
      method: 'POST',
      body: { username, password },
    }),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<User>('/auth/me'),

  robots: () => request<RobotRow[]>('/robots'),

  users: () => request<UserRow[]>('/users'),
  createUser: (body: { username: string; password: string; role: string }) =>
    request<UserRow>('/users', { method: 'POST', body }),
  updateUser: (id: number, body: { role?: string; is_active?: boolean }) =>
    request<UserRow>(`/users/${id}`, { method: 'PATCH', body }),
  resetPassword: (id: number, password: string) =>
    request<{ ok: boolean }>(`/users/${id}/password`, { method: 'POST', body: { password } }),
  deleteUser: (id: number) => request<{ ok: boolean }>(`/users/${id}`, { method: 'DELETE' }),
  status: (id = 1) => request<StatusSnapshot>(`/robots/${id}/status`),
  maps: (id = 1) => request<MapMeta[]>(`/robots/${id}/maps`),
  currentMap: (id = 1) => request<{ name: string; md5sum?: string }>(`/robots/${id}/map/current`),
  navPoints: (id = 1, mapName = '', pathName = '') =>
    request<{
      map_name: string
      path_name: string
      /** 服务端已解析好的点位（theta 为弧度），前端不再重复实现解析器 */
      points: NavPoint[]
      /** 原文，写回时未修改的行要原样保留 */
      path_data: string
    }>(
      `/robots/${id}/nav-points?map_name=${encodeURIComponent(mapName)}&path_name=${encodeURIComponent(pathName)}`,
    ),
  tasks: (id = 1) => request<TaskItem[]>(`/robots/${id}/tasks`),
  alarms: (activeOnly = false) => request<AlarmItem[]>(`/alarms?active=${activeOnly}`),
  ackAlarm: (alarmId: number) =>
    request<AlarmItem>(`/alarms/${alarmId}/ack`, { method: 'POST' }),
  capabilities: (id = 1) => request<Record<string, unknown>>(`/robots/${id}/capabilities`),
  probe: (id = 1) => request<Record<string, unknown>>(`/robots/${id}/probe`, { method: 'POST' }),
  precheck: (id = 1) =>
    request<{ ok: boolean; reasons: string[] }>(`/robots/${id}/commands/precheck`, { method: 'POST' }),
  mapPng: (id = 1, name = '') => `/api/v1/robots/${id}/map/png?name=${encodeURIComponent(name)}`,
  deepHealth: () =>
    request<{
      cache: { online: boolean; age_s: number; consecutive_failures: number; last_error: string | null; poll_count: number }
      services: { name: string; running: boolean; restarts: number; last_error: string | null }[]
      loop_lag_ms: number
    }>('/health/deep'),
}

export interface TaskItem {
  id: string
  name: string
  state: string
  loop_flag: boolean
  progress: number
  current_task: unknown
  sub_tasks: unknown[]
}
