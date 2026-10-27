export class ApiError extends Error {
  code: string
  status: number
  details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function cookie(name: string): string {
  const hit = document.cookie.split('; ').find((row) => row.startsWith(`${name}=`))
  return hit ? decodeURIComponent(hit.split('=').slice(1).join('=')) : ''
}

// 全局 401 处理：登录态过期时不能只在页面里弹红字，要立刻退回登录页，
// 否则大屏会一直"假装还活着"（定时轮询每 5 秒 401，但界面还是旧数据）。
type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null
let lastUnauthorizedAt = 0

export function onUnauthorized(fn: UnauthorizedHandler): void {
  unauthorizedHandler = fn
}

// 这些接口的 401 是"业务答案"，不是会话过期：
// /auth/login 密码错、/auth/me 用来判断有没有登录、/auth/logout 本来就可能没会话
const AUTH_PATHS = new Set(['/auth/login', '/auth/me', '/auth/logout'])

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  /** 文件上传用：直接传 FormData，不要 JSON 序列化，Content-Type 交给浏览器 */
  raw?: FormData
  headers?: Record<string, string>
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.body && !options.raw ? { 'Content-Type': 'application/json' } : {}),
    ...options.headers,
  }
  // 写接口走双提交 CSRF：cookie 与 header 必须一致
  if (method !== 'GET') headers['X-CSRF-Token'] = cookie('jc_csrf')

  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'include',
    body: options.raw ?? (options.body ? JSON.stringify(options.body) : undefined),
  })

  if (!res.ok) {
    if (res.status === 401 && !AUTH_PATHS.has(path)) {
      const now = Date.now()
      if (unauthorizedHandler && now - lastUnauthorizedAt > 3000) {
        lastUnauthorizedAt = now
        try { unauthorizedHandler() } catch { /* 处理函数自己兜底 */ }
      }
    }
    let code = 'HTTP_ERROR'
    let message = `请求失败（${res.status}）`
    let details: unknown
    try {
      const body = await res.json()
      code = body.code ?? code
      message = body.message ?? message
      details = body.details
    } catch {
      /* 非 JSON 响应保留默认文案 */
    }
    throw new ApiError(res.status, code, message, details)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
