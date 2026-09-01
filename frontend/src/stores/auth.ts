import { defineStore } from 'pinia'

export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'user'
}

/**
 * 认证状态（P1）：
 * - access token 30 分钟（拦截器自动续期）/ refresh 7 天；
 * - 均持久化到 localStorage，刷新页面保持登录。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('portal.token') ?? '',
    refreshToken: localStorage.getItem('portal.refresh') ?? '',
    user: JSON.parse(localStorage.getItem('portal.user') ?? 'null') as CurrentUser | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
  },
  actions: {
    setSession(token: string, refreshToken: string, user: CurrentUser) {
      this.token = token
      this.refreshToken = refreshToken
      this.user = user
      localStorage.setItem('portal.token', token)
      localStorage.setItem('portal.refresh', refreshToken)
      localStorage.setItem('portal.user', JSON.stringify(user))
    },
    setAccessToken(token: string) {
      this.token = token
      localStorage.setItem('portal.token', token)
    },
    logout() {
      this.token = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem('portal.token')
      localStorage.removeItem('portal.refresh')
      localStorage.removeItem('portal.user')
    },
  },
})
