import axios from 'axios'

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

// 响应拦截：解包统一响应，非 0 错误码转为 rejected
request.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse
    if (body.code !== 0) {
      return Promise.reject(new Error(body.message || `请求失败（${body.code}）`))
    }
    // 直接把 data 交给调用方（类型经由 api/* 函数的泛型标注）
    return body.data as unknown as typeof resp
  },
  (error) => {
    if (error.response?.status === 401) {
      // TODO(P1): 清除会话并跳转登录页
    }
    return Promise.reject(error)
  },
)

export default request
