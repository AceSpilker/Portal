import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import LoginView from '../views/LoginView.vue'
import AppLayout from '../layouts/AppLayout.vue'
import HomeView from '../views/HomeView.vue'
import AppsManageView from '../views/AppsManageView.vue'
import SettingsView from '../views/SettingsView.vue'

// 视图数量仍少，静态导入避免懒加载空窗；页面增多后再按需改回懒加载
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true },
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'home', component: HomeView, meta: { titleKey: 'nav.home' } },
        { path: 'apps', name: 'apps', component: AppsManageView, meta: { titleKey: 'apps.title' } },
        {
          path: 'settings',
          name: 'settings',
          component: SettingsView,
          meta: { titleKey: 'settings.title', requiresAdmin: true },
        },
      ],
    },
  ],
})

// 登录守卫（P1 完整实现：token 校验/续期）+ 管理页权限
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login' }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'home' }
  }
})

export default router
