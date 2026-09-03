<script setup lang="ts">
/**
 * 多入口选择浮层（M04-12）+ SSH 本地命令弹窗（M04-15；dev-plan P3.7/P3.8）。
 *
 * - 打开时调 /apps/{id}/resolve 按当前环境优先级排序：推荐入口置顶、备选随后，
 *   每个入口标注适用的环境档案；
 * - 点击普通入口直接打开（按应用 open_mode）；点击 ssh 入口转本地转发命令视图，
 *   生成 `ssh -L` 命令一键复制。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { CopyDocument as IconCopy } from '@element-plus/icons-vue'
import { networkApi } from '../api/network'
import type { ResolveResult } from '../api/network'
import type { AppUrl, PortalApp } from '../api/portal'
import { useEnvStore } from '../stores/env'
import { buildSshCommand, parseJump, suggestLocalPort } from '../utils/ssh'
import { isMobile } from '../composables/useIsMobile'

const props = defineProps<{ app: PortalApp | null }>()
const emit = defineEmits<{ choose: [app: PortalApp, url: string] }>()
const visible = defineModel<boolean>({ required: true })

const { t } = useI18n()
const envStore = useEnvStore()

const loading = ref(false)
const resolved = ref<ResolveResult | null>(null)
const step = ref<'list' | 'ssh'>('list')
const sshUrl = ref<AppUrl | null>(null)
const sshInner = ref<AppUrl | null>(null)
const localPort = ref(18000)

const entryRows = computed<AppUrl[]>(() => {
  if (!resolved.value) return []
  return [resolved.value.recommended, ...resolved.value.alternatives].filter(
    (u): u is AppUrl => u !== null,
  )
})

/** 入口适用的环境档案（其优先顺序包含该入口类型） */
function fitProfiles(url: AppUrl): string[] {
  return envStore.profiles
    .filter((p) => p.enabled && p.prefer_types.includes(url.access_type))
    .map((p) => p.name)
}

watch(visible, async (open) => {
  if (!open || !props.app) return
  step.value = 'list'
  sshUrl.value = null
  resolved.value = null
  loading.value = true
  try {
    resolved.value = await networkApi.resolveApp(props.app.id, 'auto')
  } catch (e) {
    ElMessage.error((e as Error).message)
    visible.value = false
  } finally {
    loading.value = false
  }
})

function openUrl(url: AppUrl) {
  if (!props.app) return
  if (url.access_type === 'ssh') {
    openSsh(url)
    return
  }
  emit('choose', props.app, url.url)
  visible.value = false
}

/** 非ssh 入口全集作为 -L 隧道的内网目标候选（lan 优先） */
const innerCandidates = computed<AppUrl[]>(() => {
  if (!props.app) return []
  return props.app.urls.filter((u) => u.access_type !== 'ssh')
})

function openSsh(url: AppUrl) {
  sshUrl.value = url
  sshInner.value =
    innerCandidates.value.find((u) => u.access_type === 'lan') ?? innerCandidates.value[0] ?? null
  localPort.value = suggestLocalPort(url.id)
  step.value = 'ssh'
}

const sshCommand = computed(() => {
  if (!sshUrl.value) return ''
  const cmd = buildSshCommand(sshUrl.value, sshInner.value, localPort.value)
  return cmd ?? sshUrl.value.url
})

const sshParseFail = computed(() => {
  if (!sshUrl.value) return false
  return parseJump(sshUrl.value.url) === null || (!!sshInner.value && !buildSshCommand(sshUrl.value, sshInner.value, localPort.value))
})

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(sshCommand.value)
    ElMessage.success(t('entry.copied'))
  } catch {
    ElMessage.error(t('entry.sshParseFail'))
  }
}

function backToList() {
  step.value = 'list'
  sshUrl.value = null
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="step === 'ssh' ? t('entry.sshTitle') : t('entry.pickTitle')"
    :width="isMobile ? '94%' : '520px'"
    append-to-body
  >
    <!-- 入口列表（M04-12） -->
    <div v-if="step === 'list'" v-loading="loading" class="entry-list">
      <p class="entry-desc">{{ t('entry.pickDesc', { name: app?.name ?? '' }) }}</p>
      <button
        v-for="(u, i) in entryRows"
        :key="u.id"
        type="button"
        class="entry-row"
        @click="openUrl(u)"
      >
        <span class="entry-main">
          <el-tag size="small" type="info">{{ t(`apps.urlType.${u.access_type}`) }}</el-tag>
          <el-tag v-if="i === 0" size="small" type="success" class="rec-tag">
            {{ t('entry.recommended') }}
          </el-tag>
          <span class="entry-url">{{ u.url }}</span>
        </span>
        <span class="entry-fit">
          <template v-if="fitProfiles(u).length">{{ t('entry.fitEnv') }}：{{ fitProfiles(u).join('、') }}</template>
          <template v-else>{{ t('entry.fitNone') }}</template>
        </span>
      </button>
      <p v-if="!loading && !entryRows.length" class="entry-empty">{{ t('apps.noEntry') }}</p>
    </div>

    <!-- SSH 本地转发命令（M04-15） -->
    <div v-else class="ssh-body">
      <p class="entry-desc">{{ t('entry.sshDesc', { port: localPort }) }}</p>
      <div class="ssh-row">
        <span class="ssh-label">{{ t('entry.sshLocalPort') }}</span>
        <el-input-number v-model="localPort" :min="1024" :max="65535" />
        <el-select
          v-if="innerCandidates.length > 1"
          v-model="sshInner"
          class="ssh-inner"
          value-key="id"
          size="small"
        >
          <el-option
            v-for="u in innerCandidates"
            :key="u.id"
            :label="`${t(`apps.urlType.${u.access_type}`)} · ${u.url}`"
            :value="u"
          />
        </el-select>
      </div>
      <pre class="ssh-cmd">{{ sshCommand }}</pre>
      <p v-if="!sshInner" class="ssh-warn">{{ t('entry.sshNoInner') }}</p>
      <p v-else-if="sshParseFail" class="ssh-warn">{{ t('entry.sshParseFail') }}</p>
    </div>

    <template #footer>
      <el-button v-if="step === 'ssh'" @click="backToList">{{ t('entry.back') }}</el-button>
      <el-button @click="visible = false">{{ t('common.close') }}</el-button>
      <el-button v-if="step === 'ssh'" type="primary" class="btn-gradient" :icon="IconCopy" @click="copyCommand">
        {{ t('tools.copy') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.entry-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 80px;
}
.entry-desc {
  margin: 0 0 4px;
  color: var(--p-muted);
  font-size: 12.5px;
}
.entry-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--p-card-border);
  border-radius: 10px;
  background: var(--p-card);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}
.entry-row:hover {
  border-color: var(--p-primary);
  background: color-mix(in srgb, var(--p-primary) 5%, transparent);
}
.entry-main {
  display: flex;
  align-items: center;
  gap: 6px;
}
.rec-tag {
  flex-shrink: 0;
}
.entry-url {
  font-size: 13px;
  word-break: break-all;
}
.entry-fit {
  font-size: 11.5px;
  color: var(--p-muted);
}
.entry-empty {
  color: var(--p-muted);
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
}
.ssh-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ssh-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ssh-label {
  font-size: 13px;
}
.ssh-inner {
  flex: 1;
  min-width: 180px;
}
.ssh-cmd {
  margin: 0;
  padding: 10px 12px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  font-size: 12.5px;
  word-break: break-all;
  user-select: all;
}
.ssh-warn {
  margin: 0;
  font-size: 12.5px;
  color: #d97706;
}
</style>
