import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { useAuthStore } from '../stores/auth'

/** 统一响应结构（api-spec §1）。 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

const request = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 请求拦截：附带 JWT
request.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

let refreshing: Promise<string | null> | null = null

/** 用 refresh token 静默续期；失败返回 null。 */
async function silentRefresh(): Promise<string | null> {
  const auth = useAuthStore()
  if (!auth.refreshToken) return null
  refreshing ??= axios
    .post('/api/auth/refresh', null, {
      headers: { Authorization: `Bearer ${auth.refreshToken}` },
    })
    .then((resp) => {
      const token = resp.data?.data?.access_token as string
      auth.setAccessToken(token)
      return token
    })
    .catch(() => null)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

function logoutAndRedirect() {
  const auth = useAuthStore()
  auth.logout()
  ElMessage.warning('登录已失效，请重新登录')
  if (router.currentRoute.value.name !== 'login') {
    router.push({ name: 'login' })
  }
}

// 响应拦截：解包统一响应 + 401 静默续期
request.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body.code !== 0) {
      return Promise.reject(new Error(body.message || `请求失败（${body.code}）`))
    }
    // 直接把 data 交给调用方（类型经由 api/* 函数的泛型标注）
    return body.data as unknown as typeof resp
  },
  async (error) => {
    const status = error.response?.status
    const code = error.response?.data?.code as number | undefined
    const original = error.config as (typeof error.config & { _retried?: boolean }) | undefined

    // 401：access 过期 → 静默续期一次并重试；其余登出
    if (status === 401 && original && !original._retried) {
      if (code === 1003 || code === undefined || code === 1002) {
        const newToken = await silentRefresh()
        if (newToken) {
          original._retried = true
          original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` }
          return request(original)
        }
      }
      logoutAndRedirect()
    }
    return Promise.reject(error)
  },
)

export default request
