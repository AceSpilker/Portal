/** 路由守卫与 404 兜底回归（065 用户反馈：未知路径白屏、未登录直达受保护页无提示）。 */
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '../router'
import { useAuthStore } from '../stores/auth'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('router catch-all', () => {
  it('未知路径解析到 not-found 页（public，不再白屏）', async () => {
    await router.push('/no-such-page-xyz')
    expect(router.currentRoute.value.name).toBe('not-found')
  })

  it('多级未知路径同样兜底', async () => {
    await router.push('/a/b/c')
    expect(router.currentRoute.value.name).toBe('not-found')
  })
})

describe('登录守卫', () => {
  it('未登录直达受保护路由 → 重定向 login', async () => {
    const auth = useAuthStore()
    auth.logout()
    await router.push('/apps')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('已登录可正常进入受保护路由', async () => {
    const auth = useAuthStore()
    auth.setSession('fake-token', 'fake-refresh', { id: 1, username: 'tester', role: 'admin' })
    await router.push('/apps')
    expect(router.currentRoute.value.name).toBe('apps')
  })
})
