import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import i18n from '../locales'
import { useAuthStore } from '../stores/auth'
import LoginView from '../views/LoginView.vue'
import GuestView from '../views/GuestView.vue'
import NotFoundView from '../views/NotFoundView.vue'
import AppLayout from '../layouts/AppLayout.vue'
import HomeView from '../views/HomeView.vue'
import AppsManageView from '../views/AppsManageView.vue'
import EfficiencyView from '../views/EfficiencyView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import PortsView from '../views/PortsView.vue'
import DockerView from '../views/DockerView.vue'
import AiView from '../views/AiView.vue'
import FlowView from '../views/FlowView.vue'
import MonitorView from '../views/MonitorView.vue'
import SettingsView from '../views/SettingsView.vue'
import ToolsView from '../views/ToolsView.vue'
import LogsView from '../views/LogsView.vue'

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
      path: '/guest',
      name: 'guest',
      component: GuestView,
      meta: { public: true },
    },
    {
      // 404 兜底（065 用户实测：未知路径原先白屏/裸 JSON）
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: NotFoundView,
      meta: { public: true },
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'home', component: HomeView, meta: { titleKey: 'nav.home' } },
        { path: 'apps', name: 'apps', component: AppsManageView, meta: { titleKey: 'apps.title' } },
        { path: 'efficiency', name: 'efficiency', component: EfficiencyView, meta: { titleKey: 'nav.efficiency' } },
        { path: 'knowledge', name: 'knowledge', component: KnowledgeView, meta: { titleKey: 'nav.knowledge' } },
        { path: 'ports', name: 'ports', component: PortsView, meta: { titleKey: 'nav.ports' } },
        { path: 'docker', name: 'docker', component: DockerView, meta: { titleKey: 'nav.docker' } },
        { path: 'ai', name: 'ai', component: AiView, meta: { titleKey: 'nav.ai' } },
        { path: 'flow', name: 'flow', component: FlowView, meta: { titleKey: 'nav.flow' } },
        {
          path: 'monitor',
          name: 'monitor',
          component: MonitorView,
          meta: { titleKey: 'nav.monitor' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: SettingsView,
          meta: { titleKey: 'settings.title', requiresAdmin: true },
        },
        { path: 'tools', name: 'tools', component: ToolsView, meta: { titleKey: 'nav.tools' } },
        { path: 'logs', name: 'logs', component: LogsView, meta: { titleKey: 'nav.logs', requiresAdmin: true } },
      ],
    },
  ],
})

// 登录守卫（P1 完整实现：token 校验/续期）+ 管理页权限
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    // 未登录直达受保护路由：回登录页并提示（065 用户反馈原先静默跳转无感知）
    ElMessage.warning(i18n.global.t('request.loginRequired'))
    return { name: 'login' }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'home' }
  }
})

export default router
