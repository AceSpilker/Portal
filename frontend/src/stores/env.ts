import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { networkApi } from '../api/network'
import type { DetectResult, NetworkProfile } from '../api/network'

/**
 * 网络环境状态（M04-8/9；dev-plan P3）：
 * - 登录后由布局加载：自动识别当前环境 + 档案列表（顶栏切换器数据源）；
 * - 手动偏好经 PUT /me/env 持久化（服务端记忆），null 恢复自动识别。
 */
export const useEnvStore = defineStore('env', () => {
  const profiles = ref<NetworkProfile[]>([])
  const clientIp = ref('')
  const autoProfile = ref<NetworkProfile | null>(null)
  const manualProfile = ref<NetworkProfile | null>(null)
  const loaded = ref(false)

  async function load(force = false) {
    if (loaded.value && !force) return
    try {
      const [detected, list, myEnv] = await Promise.all([
        networkApi.detect() as Promise<DetectResult>,
        networkApi.listProfiles(),
        networkApi.getMyEnv(),
      ])
      clientIp.value = detected.client_ip
      autoProfile.value = detected.matched_profile
      profiles.value = list
      manualProfile.value = myEnv.manual_profile
      loaded.value = true
    } catch {
      // 未登录或接口异常时静默，顶栏显示「检测中」
    }
  }

  /** 手动切换环境（M04-9）：profileId=null 恢复自动。 */
  async function setManual(profileId: number | null) {
    const result = await networkApi.setMyEnv(profileId)
    manualProfile.value = result.manual_profile
    autoProfile.value = result.auto_profile
  }

  /** 生效环境 = 手动优先，其次自动识别。 */
  const effective = computed(() => manualProfile.value ?? autoProfile.value)

  function reset() {
    profiles.value = []
    clientIp.value = ''
    autoProfile.value = null
    manualProfile.value = null
    loaded.value = false
  }

  return {
    profiles,
    clientIp,
    autoProfile,
    manualProfile,
    loaded,
    effective,
    load,
    setManual,
    reset,
  }
})
