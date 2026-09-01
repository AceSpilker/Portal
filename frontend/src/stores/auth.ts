import { defineStore } from 'pinia'

export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'user'
}

/**
 * 认证状态（P1 接入真实 JWT 流程）。
 * token 持久化于 localStorage；P1 增加 refresh 续期与踢出逻辑。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('portal.token') ?? '',
    user: JSON.parse(localStorage.getItem('portal.user') ?? 'null') as CurrentUser | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
  },
  actions: {
    setSession(token: string, user: CurrentUser) {
      this.token = token
      this.user = user
      localStorage.setItem('portal.token', token)
      localStorage.setItem('portal.user', JSON.stringify(user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('portal.token')
      localStorage.removeItem('portal.user')
    },
  },
})
