/**
 * 应用探活状态（M07-2；dev-plan P6.3）。
 *
 * 首次登录后连接 /ws/notify（登录用户均可订阅），状态变化即时写入映射；
 * 页面初始加载经 /probe/status 拉一次全量。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { probeApi, type ProbeState, type ProbeStatus } from '../api/probe'

export const useProbeStore = defineStore('probe', () => {
  const statusMap = ref<Record<string, ProbeStatus>>({})
  const connected = ref(false)
  let ws: WebSocket | null = null
  let retryTimer: number | undefined
  let retryDelay = 3000
  let started = false

  function apply(e: { app_id: number; state: ProbeState; latency: number | null; message: string }) {
    statusMap.value = {
      ...statusMap.value,
      [String(e.app_id)]: { state: e.state, latency_ms: e.latency, message: e.message ?? '' },
    }
  }

  function connect(token: string) {
    if (ws || !token) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/notify?token=${encodeURIComponent(token)}`)
    ws.onopen = () => {
      connected.value = true
      retryDelay = 3000
      void probeApi.status().then(load)
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'app_status') apply(msg.data)
      } catch {
        /* 忽略坏帧 */
      }
    }
    ws.onclose = () => {
      ws = null
      connected.value = false
      retryTimer = window.setTimeout(() => connect(token), retryDelay)
      retryDelay = Math.min(retryDelay * 2, 60_000)
    }
  }

  async function load() {
    try {
      statusMap.value = { ...statusMap.value, ...(await probeApi.status()) }
    } catch {
      /* 未登录/无权限时静默 */
    }
  }

  function start(token: string) {
    if (started) return
    started = true
    void load()
    connect(token)
  }

  function stop() {
    started = false
    window.clearTimeout(retryTimer)
    ws?.close()
    ws = null
  }

  return { statusMap, connected, start, stop, load, apply }
})
