import axios from 'axios'
import request from './request'
import type { CurrentUser } from '../stores/auth'

export interface TokenResp {
  access_token: string
  refresh_token: string
  user: CurrentUser
  site_name?: string
}

async function axiosPostRefresh(refreshToken: string): Promise<{ access_token: string }> {
  const resp = await axios.post('/api/auth/refresh', null, {
    headers: { Authorization: `Bearer ${refreshToken}` },
  })
  return resp.data.data
}

export const authApi = {
  /** 首次初始化（仅无用户时可用） */
  init: (payload: { username: string; password: string; site_name: string }) =>
    request.post<never, TokenResp>('/auth/init', payload),
  /** 登录 */
  login: (payload: { username: string; password: string }) =>
    request.post<never, TokenResp>('/auth/login', payload),
  /** 当前用户 */
  me: () => request.get<never, CurrentUser>('/auth/me'),
  /** 修改密码（改密后所有旧会话失效） */
  changePassword: (payload: { old_password: string; new_password: string }) =>
    request.put<never, null>('/auth/password', payload),
  /** 用 refresh token 换新 access token */
  refresh: axiosPostRefresh,
}
