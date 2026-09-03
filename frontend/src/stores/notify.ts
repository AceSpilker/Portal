/**
 * 通知中心状态（M09-1/2；dev-plan P9.2）。
 *
 * 初始加载未读角标；WS /ws/notify 的 notification 事件由 probe store 转发到
 * onWsEvent（实时插入 + 角标自增）；列表拉取带级别/未读筛选。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { notifyApi, type NotificationItem, type NotifyLevel } from '../api/notify'

export const useNotifyStore = defineStore('notify', () => {
  const unread = ref(0)
  const items = ref<NotificationItem[]>([])
  const levelFilter = ref<NotifyLevel | ''>('')
  const unreadOnly = ref(false)
  const loaded = ref(false)

  async function refreshUnread() {
    try {
      unread.value = (await notifyApi.unreadCount()).unread
    } catch {
      /* 未登录/断线时静默 */
    }
  }

  async function load() {
    try {
      const params: Record<string, unknown> = { limit: 30 }
      if (levelFilter.value) params.level = levelFilter.value
      if (unreadOnly.value) params.unread = 1
      const page = await notifyApi.list(params)
      items.value = page.items
      unread.value = page.unread
      loaded.value = true
    } catch {
      /* 静默 */
    }
  }

  /** probe store 的 WS onmessage 转发入口（type=notification）。 */
  function onWsEvent(data: NotificationItem) {
    items.value = [data, ...items.value].slice(0, 50)
    if (!data.is_read) unread.value += 1
  }

  async function markRead(id: number) {
    const item = items.value.find((i) => i.id === id)
    if (item && !item.is_read) {
      item.is_read = true
      unread.value = Math.max(0, unread.value - 1)
    }
    await notifyApi.markRead(id)
  }

  async function readAll() {
    await notifyApi.readAll()
    items.value = items.value.map((i) => ({ ...i, is_read: true }))
    unread.value = 0
  }

  async function remove(id: number) {
    const item = items.value.find((i) => i.id === id)
    items.value = items.value.filter((i) => i.id !== id)
    if (item && !item.is_read) unread.value = Math.max(0, unread.value - 1)
    await notifyApi.remove(id)
  }

  function setLevel(v: NotifyLevel | '') {
    levelFilter.value = v
    void load()
  }

  function setUnreadOnly(v: boolean) {
    unreadOnly.value = v
    void load()
  }

  return {
    unread,
    items,
    levelFilter,
    unreadOnly,
    loaded,
    refreshUnread,
    load,
    onWsEvent,
    markRead,
    readAll,
    remove,
    setLevel,
    setUnreadOnly,
  }
})
