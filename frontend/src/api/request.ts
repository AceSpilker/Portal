import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { useAuthStore } from '../stores/auth'
import {
  decryptBody,
  encryptBody,
  encryptHeaderValue,
  ensureSession,
  isExemptPath,
  resetSession,
} from './secure'

/** 统一响应结构（api-spec §1）。 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 标记 refresh 请求，避免静默续期递归 */
    _isRefresh?: boolean
    /** 401 重试标记 */
    _retried?: boolean
    /** 加密前的原始请求体（重试时恢复用） */
    _raw?: unknown
  }
}

const request = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 请求拦截：附 JWT（密文化）+ 信封加密请求体
request.interceptors.request.use(async (config) => {
  const auth = useAuthStore()
  if (isExemptPath(config.url ?? '')) {
    return config
  }
  await ensureSession()
  if (auth.token) {
    config.headers.Authorization = await encryptHeaderValue(`Bearer ${auth.token}`)
  }
  if (config.data !== undefined && config.data !== null) {
    ;(config as typeof config & { _raw?: unknown })._raw = config.data
    const encrypted = await encryptBody(config.url ?? '', config.data)
    config.data = encrypted.body
    if (encrypted.sessionId) {
      config.headers['X-Session-Id'] = encrypted.sessionId
    }
  }
  return config
})

let refreshing: Promise<string | null> | null = null

/** 用 refresh token 静默续期；失败返回 null。 */
async function silentRefresh(): Promise<string | null> {
  const auth = useAuthStore()
  if (!auth.refreshToken) return null
  refreshing ??= (async () => {
    try {
      const resp = await request.post('/auth/refresh', null, { _isRefresh: true })
      const token = (resp as unknown as { access_token: string }).access_token
      auth.setAccessToken(token)
      return token
    } catch {
      return null
    }
  })().finally(() => {
    refreshing = null
  })
  return refreshing
}

function logoutAndRedirect() {
  const auth = useAuthStore()
  auth.logout()
  if (router.currentRoute.value.name !== 'login') {
    ElMessage.warning('登录已失效，请重新登录')
    router.push({ name: 'login' })
  }
}

// 响应拦截：解密信封 → 解包统一响应 → 401 静默续期 → 1100 重新握手
request.interceptors.response.use(
  async (resp) => {
    const data = await decryptBody(resp.data)
    const body = data as ApiResponse
    if (body.code !== 0) {
      return Promise.reject(new Error(body.message || `请求失败（${body.code}）`))
    }
    return body.data as never
  },
  async (error) => {
    const status = error.response?.status
    const body = error.response?.data as Record<string, unknown> | undefined
    const code = typeof body?.code === 'number' ? body.code : undefined
    const original = error.config as (typeof error.config & {
      _retried?: boolean
      _raw?: unknown
      _isRefresh?: boolean
    }) | undefined

    // 加密会话失效（服务端重启等）→ 重新握手并重试一次
    if (code === 1100 && original && !original._retried) {
      original._retried = true
      resetSession()
      await ensureSession()
      if (original._raw !== undefined) original.data = original._raw
      return request(original)
    }

    // 401：access 过期 → 静默续期一次并重试；refresh 请求自身失败则登出
    if (status === 401 && original && !original._retried && !original._isRefresh) {
      const newToken = await silentRefresh()
      if (newToken) {
        original._retried = true
        if (original._raw !== undefined) original.data = original._raw
        return request(original)
      }
      logoutAndRedirect()
    }
    return Promise.reject(error)
  },
)

export default request
