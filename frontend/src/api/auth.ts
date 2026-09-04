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
  /** 登录（totp_code：两步验证码/恢复码，P17.1） */
  login: (payload: { username: string; password: string; totp_code?: string }) =>
    request.post<never, TokenResp>('/auth/login', payload),
  /** 开放注册（P17.3：security.allow_register 开启时可用） */
  register: (payload: { username: string; password: string }) =>
    request.post<never, { id: number; username: string }>('/auth/register', payload),
  /** LDAP 企业登录（P22.1） */
  ldapLogin: (payload: { username: string; password: string }) =>
    request.post<never, TokenResp>('/auth/ldap/login', payload),
  /** 公开配置（注册开关等） */
  config: () => request.get<never, { allow_register: boolean }>('/auth/config'),
  /** TOTP：生成密钥 / 启用 / 关闭（P17.1） */
  totpSetup: () => request.post<never, { secret: string; otpauth_uri: string }>('/auth/totp/setup'),
  totpEnable: (code: string) =>
    request.post<never, { recovery_codes: string[] }>('/auth/totp/enable', { code }),
  totpDisable: (password: string, code: string) =>
    request.post<never, null>('/auth/totp/disable', { password, code }),
  /** 会话/设备管理（P17.1） */
  sessions: () => request.get<never, Array<{ id: number; device: string; ip: string; created_at: string | null; last_seen_at: string | null; revoked: boolean }>>('/auth/sessions'),
  revokeSession: (id: number) => request.delete<never, { id: number }>(`/auth/sessions/${id}`),
  /** 当前用户 */
  me: () => request.get<never, CurrentUser>('/auth/me'),
  /** 修改密码（改密后所有旧会话失效） */
  changePassword: (payload: { old_password: string; new_password: string }) =>
    request.put<never, null>('/auth/password', payload),
  /** 用 refresh token 换新 access token */
  refresh: axiosPostRefresh,
}
