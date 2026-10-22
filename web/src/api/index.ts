import { request } from './client'

export type Role = 'admin' | 'safety' | 'operator' | 'viewer'

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

export interface RecordingItem {
  path: string
  video_id: number
  started_at: string
  size: number
  mtime: number
}

export interface UserRow {
  id: number
  username: string
  role: 'admin' | 'safety' | 'operator' | 'viewer'
  is_active: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface VideoRow {
  show_on_dashboard?: boolean
  id: number
  name: string
  group_name: string
  vendor: 'hikvision' | 'dahua' | 'other'
  url: string
  enabled: boolean
  note: string | null
  stream_name: string
  play_url: string | null
  go2rtc_url: string | null
}

export interface DeviceItem {
  id: number
  name: string
  device_type: string
  adapter: string
  adapter_label: string
  supported: boolean
  station: string
  ip: string
  port: number
  ws_port: number
  username: string | null
  mode: string
  is_active: boolean
  version: string | null
  slam_type: string | null
  last_seen: string | null
  note: string | null
  needs: string[]
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

export interface AuditItem {
  id: number
  ts: string | null
  username: string | null
  client_ip: string | null
  action: string
  target: string | null
  success: boolean
  summary: string | null
  detail: string | null
}

export interface SensorKind {
  value: string
  label: string
  unit: string
}

export interface SensorItem {
  id: number
  name: string
  kind: string
  kind_label: string
  unit: string
  station: string
  location: string | null
  serial: string | null
  warn_low: number | null
  warn_high: number | null
  crit_low: number | null
  crit_high: number | null
  enabled: boolean
  note: string | null
  calibrated: boolean
  latest: { value: number; ts: string; source: string } | null
}

export interface LibraryMap {
  id: number
  name: string
  floor: string
  station: string
  resolution: number
  origin: [number, number, number]
  width: number
  height: number
  robot_map_name: string | null
  is_active: boolean
  note: string | null
  created_at: string | null
  draft_points: number
}

export interface PointDraft {
  id: number
  name: string
  group?: string
  x: number
  y: number
  theta: number
  note: string | null
  synced: boolean
}

export interface AlarmPage {
  total: number
  items: AlarmItem[]
}

export interface AlarmItem {
  status?: 'new' | 'acked' | 'handled' | 'closed'
  handled_at?: string | null
  handled_by?: string | null
  handle_note?: string | null
  closed_at?: string | null
  closed_by?: string | null
  resolution?: string | null
  close_note?: string | null
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
  verifyPassword: (password: string) =>
    request<{ ok: boolean }>('/auth/verify', { method: 'POST', body: { password } }),
  changePassword: (old_password: string, new_password: string) =>
    request<{ ok: boolean }>('/auth/password', { method: 'POST', body: { old_password, new_password } }),
  me: () => request<User>('/auth/me'),

  robots: () => request<RobotRow[]>('/robots'),

  // 设备台账（多设备）
  devices: () => request<DeviceItem[]>('/devices'),
  deviceMeta: () => request<{ device_types: { value: string; label: string }[]; adapters: Record<string, { label: string; device_type: string; supported: boolean; needs: string[]; note: string }> }>('/devices/meta'),
  createDevice: (body: Record<string, unknown>) =>
    request<DeviceItem>('/devices', { method: 'POST', body }),
  updateDevice: (id: number, body: Record<string, unknown>) =>
    request<DeviceItem>(`/devices/${id}`, { method: 'PATCH', body }),
  deleteDevice: (id: number) => request<{ ok: boolean }>(`/devices/${id}`, { method: 'DELETE' }),
  testDevice: (id: number) =>
    request<{ tcp: boolean; http: boolean; detail: string }>(`/devices/${id}/test`, { method: 'POST' }),

  videos: () => request<VideoRow[]>('/videos'),
  registerGo2rtc: (id: number) =>
    request<{ ok: boolean; stream: string; web_stream: string; video: VideoRow }>(`/videos/${id}/register-go2rtc`, { method: 'POST' }),
  go2rtcStreams: () => request<{ ok: boolean; reason?: string; streams: { name: string; source: string; web: boolean; ready: boolean }[] }>('/videos/go2rtc-streams'),
  createVideo: (body: { name: string; group_name: string; vendor: string; url: string; note?: string | null; stream_name?: string }) =>
    request<VideoRow>('/videos', { method: 'POST', body }),
  updateVideo: (id: number, body: Partial<{ name: string; group_name: string; vendor: string; url: string; enabled: boolean; show_on_dashboard: boolean; note: string | null; stream_name: string }>) =>
    request<VideoRow>(`/videos/${id}`, { method: 'PATCH', body }),
  snapshotUrl: (id: number, tick: number) => `/api/v1/videos/${id}/snapshot?t=${tick}`,
  testVideo: (id: number) =>
    request<{ ok: boolean; target: string; message: string }>(`/videos/${id}/test`, { method: 'POST' }),
  deleteVideo: (id: number) => request<{ ok: boolean }>(`/videos/${id}`, { method: 'DELETE' }),

  auditLogs: (params: Record<string, string | number | undefined> = {}) => {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&')
    return request<{ total: number; items: AuditItem[] }>(`/audit-logs${qs ? `?${qs}` : ''}`)
  },
  // 告警通知
  notifyMeta: () => request<{ types: { value: string; label: string }[]; levels: { value: string; label: string }[] }>('/notify/meta'),
  notifyChannels: () => request<Record<string, unknown>[]>('/notify/channels'),
  createNotifyChannel: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/notify/channels', { method: 'POST', body }),
  updateNotifyChannel: (id: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/notify/channels/${id}`, { method: 'PATCH', body }),
  deleteNotifyChannel: (id: number) =>
    request<{ ok: boolean }>(`/notify/channels/${id}`, { method: 'DELETE' }),
  testNotifyChannel: (id: number) =>
    request<{ ok: boolean; status: string }>(`/notify/channels/${id}/test`, { method: 'POST' }),
  notifyLogs: (params: { limit?: number; offset?: number; only_failed?: boolean } = {}) => {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&')
    return request<{ total: number; items: Record<string, unknown>[] }>(`/notify/logs${qs ? `?${qs}` : ''}`)
  },
  reportSummary: (dateFrom?: string, dateTo?: string) => {
    const q: string[] = []
    if (dateFrom) q.push(`date_from=${dateFrom}`)
    if (dateTo) q.push(`date_to=${dateTo}`)
    return request<Record<string, unknown>>(`/reports/summary${q.length ? '?' + q.join('&') : ''}`)
  },
  taskRuns: (params: { status?: string; limit?: number } = {}) => {
    const qs = Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
    return request<{ total: number; items: Record<string, unknown>[] }>(`/task-runs${qs ? '?' + qs : ''}`)
  },
  taskRun: (id: number) => request<Record<string, unknown>>(`/task-runs/${id}`),
  createTaskRun: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/task-runs', { method: 'POST', body }),
  cancelTaskRun: (id: number) =>
    request<Record<string, unknown>>(`/task-runs/${id}/cancel`, { method: 'POST' }),
  taskTemplates: () => request<Record<string, unknown>[]>('/task-templates'),
  taskTemplateMeta: () => request<{ actions: { value: string; label: string }[] }>('/task-templates/meta'),
  createTaskTemplate: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/task-templates', { method: 'POST', body }),
  updateTaskTemplate: (id: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/task-templates/${id}`, { method: 'PATCH', body }),
  deleteTaskTemplate: (id: number) =>
    request<{ ok: boolean }>(`/task-templates/${id}`, { method: 'DELETE' }),
  dispatchTaskTemplate: (id: number) =>
    request<{ ok: boolean }>(`/task-templates/${id}/dispatch`, { method: 'POST' }),
  messages: () => request<{ items: { id: number; ts: number; level: string; source: string; title: string; body: string; link: Record<string, unknown> }[]; unread: number }>('/messages'),

  // 录像
  recordings: (videoId?: number) =>
    request<{ total: number; items: RecordingItem[]; recording: { video_id: number; name: string; running: boolean; started_at: number }[] }>(
      `/recordings${videoId ? `?video_id=${videoId}` : ''}`),
  recordPlans: () => request<Record<string, unknown>[]>('/record-plans'),
  createRecordPlan: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/record-plans', { method: 'POST', body }),
  updateRecordPlan: (id: number, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/record-plans/${id}`, { method: 'PATCH', body }),
  deleteRecordPlan: (id: number) =>
    request<{ ok: boolean }>(`/record-plans/${id}`, { method: 'DELETE' }),
  recordingStatus: () =>
    request<{
      recorders: { video_id: number; name: string; running: boolean; started_at: number }[]
      ffmpeg: boolean
      enabled: boolean
      keep_days: number
      max_gb: number
    }>('/recordings/status'),
  startRecording: (videoId: number) =>
    request<{ ok: boolean; video_id: number; running: boolean }>(`/recordings/${videoId}/start`, { method: 'POST' }),
  stopRecording: (videoId: number) =>
    request<{ ok: boolean; video_id: number }>(`/recordings/${videoId}/stop`, { method: 'POST' }),
  recordingFileUrl: (path: string) => `/api/v1/recordings/file?path=${encodeURIComponent(path)}`,
  deleteRecording: (path: string) =>
    request<{ ok: boolean }>(`/recordings/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  recordingStorage: () => request<{ files: number; bytes: number; dir: string }>('/recordings/storage'),
  recordingDuration: (path: string) =>
    request<{ path: string; duration: number | null }>(`/recordings/duration?path=${encodeURIComponent(path)}`),

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

  // 平台地图库（导入/标定/草稿点位）
  libraryMaps: () => request<LibraryMap[]>('/maps/library'),
  libraryImageUrl: (id: number) => `/api/v1/maps/library/${id}/image`,
  importLibraryMap: (fd: FormData) => request<LibraryMap>('/maps/library', { method: 'POST', raw: fd }),
  libraryPoints: (id: number) => request<PointDraft[]>(`/maps/library/${id}/points`),
  addLibraryPoint: (id: number, body: { name: string; x: number; y: number; note?: string | null }) =>
    request<PointDraft>(`/maps/library/${id}/points`, { method: 'POST', body }),
  importPoints: (mapId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<{ created: number; updated: number; errors: string[]; total: number }>(
      `/maps/library/${mapId}/points/import`, { method: 'POST', raw: fd })
  },
  exportPointsUrl: (mapId: number) => `/api/v1/maps/library/${mapId}/points/export`,
  bulkPoints: (mapId: number, body: { ids: number[]; action: 'group' | 'delete' | 'note'; group?: string | null; note?: string | null }) =>
    request<{ ok: boolean; affected: number; action: string }>(`/maps/library/${mapId}/points/bulk`, { method: 'PATCH', body }),
  duplicateTaskTemplate: (id: number) =>
    request<Record<string, unknown>>(`/task-templates/${id}/duplicate`, { method: 'POST' }),
  deleteLibraryPoint: (pointId: number) =>
    request<{ ok: boolean }>(`/maps/library/points/${pointId}`, { method: 'DELETE' }),
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
  alarms: (activeOnly = false) =>
    request<AlarmPage>(`/alarms?limit=200${activeOnly ? '&status=unacked' : ''}`),
  alarmStats: (days = 7) =>
    request<{ days: number; series: { date: string; warn: number; critical: number; total: number }[];
              total: number; unacked: number; acked: number; peak: number }>(`/alarms/stats?days=${days}`),
  handleAlarm: (id: number, note: string) =>
    request<AlarmItem>(`/alarms/${id}/handle`, { method: 'POST', body: { note } }),
  closeAlarm: (id: number, resolution: string, note: string) =>
    request<AlarmItem>(`/alarms/${id}/close`, { method: 'POST', body: { resolution, note } }),
  alarmQuery: (params: Record<string, string | number | undefined>) => {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
      .join('&')
    return request<AlarmPage>(`/alarms${qs ? `?${qs}` : ''}`)
  },
  ackAlarm: (alarmId: number) =>
    request<AlarmItem>(`/alarms/${alarmId}/ack`, { method: 'POST' }),
  capabilities: (id = 1) => request<Record<string, unknown>>(`/robots/${id}/capabilities`),
  probe: (id = 1) => request<Record<string, unknown>>(`/robots/${id}/probe`, { method: 'POST' }),
  precheck: (id = 1) =>
    request<{ ok: boolean; reasons: string[] }>(`/robots/${id}/commands/precheck`, { method: 'POST' }),
  mapPng: (id = 1, name = '') => `/api/v1/robots/${id}/map/png?name=${encodeURIComponent(name)}`,
  settings: () =>
    request<{ values: Record<string, unknown>; schema: Record<string, unknown>[]; meta: Record<string, unknown> }>('/settings'),
  saveSettings: (values: Record<string, unknown>) =>
    request<{ ok: boolean; values: Record<string, unknown>; changed: Record<string, unknown> }>('/settings', { method: 'PUT', body: { values } }),
  // 环境传感器
  sensors: () => request<SensorItem[]>('/sensors'),
  sensorMeta: () => request<{ kinds: SensorKind[] }>('/sensors/meta'),
  createSensor: (body: Record<string, unknown>) =>
    request<SensorItem>('/sensors', { method: 'POST', body }),
  updateSensor: (id: number, body: Record<string, unknown>) =>
    request<SensorItem>(`/sensors/${id}`, { method: 'PATCH', body }),
  deleteSensor: (id: number) => request<{ ok: boolean }>(`/sensors/${id}`, { method: 'DELETE' }),
  addSensorReading: (id: number, value: number, source = 'manual') =>
    request<{ ok: boolean; id: number; level: string | null; message: string; raised: boolean }>(
      `/sensors/${id}/readings`, { method: 'POST', body: { value, source } }),
  sensorHistory: (id: number, hours = 24, points = 60) =>
    request<{ sensor_id: number; unit: string; points: { ts: string; value: number }[]; count: number }>(
      `/sensors/${id}/history?hours=${hours}&points=${points}`),
  sensorSummary: () =>
    request<{ items: Record<string, { name: string; unit: string; value: number | null; ts: string | null; calibrated: boolean }>; count: number }>('/sensors/summary'),
  telemetry: (hours = 24, points = 240) =>
    request<{
      count: number
      hours: number
      series: { ts: string; battery: number | null; speed: number | null; voltage: number | null; online: boolean }[]
      stats: { battery_min: number | null; battery_max: number | null; battery_avg: number | null;
               speed_max: number | null; distance_m: number; offline_ratio: number; from: string; to: string } | null
    }>(`/telemetry?hours=${hours}&points=${points}`),
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
