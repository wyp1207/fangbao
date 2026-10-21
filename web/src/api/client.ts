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

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...options.headers,
  }
  // 写接口走双提交 CSRF：cookie 与 header 必须一致
  if (method !== 'GET') headers['X-CSRF-Token'] = cookie('jc_csrf')

  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'include',
    body: options.body ? JSON.stringify(options.body) : undefined,
  })

  if (!res.ok) {
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
