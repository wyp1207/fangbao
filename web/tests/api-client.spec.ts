import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from '@/api/client'

function mockFetch(status: number, body: unknown, jsonThrows = false) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: jsonThrows ? () => Promise.reject(new Error('not json')) : () => Promise.resolve(body),
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api client', () => {
  beforeEach(() => {
    document.cookie = 'jc_csrf=tok123'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    document.cookie = 'jc_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('GET 不带 CSRF，POST 带双提交令牌', async () => {
    const f = mockFetch(200, { ok: true })
    await request('/a')
    expect(f.mock.calls[0][1].headers['X-CSRF-Token']).toBeUndefined()
    await request('/b', { method: 'POST', body: { x: 1 } })
    expect(f.mock.calls[1][1].headers['X-CSRF-Token']).toBe('tok123')
    expect(f.mock.calls[1][1].headers['Content-Type']).toBe('application/json')
  })

  it('文件上传不设 Content-Type，交给浏览器加 boundary', async () => {
    const f = mockFetch(200, { ok: true })
    const fd = new FormData()
    fd.append('file', new Blob(['x']), 'a.png')
    await request('/upload', { method: 'POST', raw: fd })
    expect(f.mock.calls[0][1].headers['Content-Type']).toBeUndefined()
    expect(f.mock.calls[0][1].body).toBeInstanceOf(FormData)
  })

  it('结构化错误转成 ApiError 并保留 code', async () => {
    mockFetch(400, { code: 'FORBIDDEN', message: '没有权限' })
    await expect(request('/x', { method: 'PUT', body: {} })).rejects.toMatchObject({
      status: 400,
      code: 'FORBIDDEN',
      message: '没有权限',
    })
  })

  it('非 JSON 错误也要有可读文案', async () => {
    mockFetch(500, null, true)
    const err = await request('/x').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(500)
    expect(err.message).toContain('500')
  })

  it('204 返回 undefined 而不是解析失败', async () => {
    mockFetch(204, null, true)
    await expect(request('/x')).resolves.toBeUndefined()
  })
})
