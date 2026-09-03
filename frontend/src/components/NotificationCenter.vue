<script setup lang="ts">
/**
 * 顶栏通知中心（M09-1/2/3；dev-plan P9.2）：铃铛 + 角标 + 下拉列表。
 * 级别筛选 / 仅看未读 / 单条已读 / 全部已读 / 删除；实时由 WS 推送（probe store 转发）。
 */
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bell, CircleCheck, Delete } from '@element-plus/icons-vue'
import { useNotifyStore } from '../stores/notify'

const { t } = useI18n()
const store = useNotifyStore()

onMounted(() => {
  void store.refreshUnread()
})

const LEVEL_CLASS: Record<string, string> = { info: 'info', warn: 'warn', error: 'error' }

function timeLabel(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <el-popover placement="bottom-end" :width="380" trigger="click" popper-class="notify-popper" @show="store.load()">
    <template #reference>
      <button type="button" class="notify-bell" :title="t('notify.title')">
        <el-badge :value="store.unread" :hidden="store.unread === 0" :max="99">
          <el-icon :size="17"><Bell /></el-icon>
        </el-badge>
      </button>
    </template>

    <div class="notify-panel">
      <header class="notify-head">
        <strong>{{ t('notify.title') }}</strong>
        <div class="notify-head-actions">
          <el-button link size="small" :icon="CircleCheck" @click="store.readAll()">
            {{ t('notify.readAll') }}
          </el-button>
        </div>
      </header>

      <div class="notify-filters">
        <el-radio-group :model-value="store.levelFilter" size="small" @update:model-value="store.setLevel($event)">
          <el-radio-button value="">{{ t('notify.levelAll') }}</el-radio-button>
          <el-radio-button value="info">{{ t('notify.levelInfo') }}</el-radio-button>
          <el-radio-button value="warn">{{ t('notify.levelWarn') }}</el-radio-button>
          <el-radio-button value="error">{{ t('notify.levelError') }}</el-radio-button>
        </el-radio-group>
        <el-checkbox
          :model-value="store.unreadOnly"
          size="small"
          @update:model-value="store.setUnreadOnly($event)"
        >
          {{ t('notify.unreadOnly') }}
        </el-checkbox>
      </div>

      <div v-if="store.items.length === 0" class="notify-empty">{{ t('notify.empty') }}</div>
      <div v-else class="notify-list">
        <div
          v-for="n in store.items"
          :key="n.id"
          class="notify-item"
          :class="[LEVEL_CLASS[n.level], { unread: !n.is_read }]"
        >
          <div class="notify-item-main" @click="!n.is_read && store.markRead(n.id)">
            <div class="notify-item-title">
              <span class="dot" />
              {{ n.title }}
            </div>
            <div v-if="n.body" class="notify-item-body">{{ n.body }}</div>
            <div class="notify-item-meta">{{ timeLabel(n.created_at) }} · {{ n.source }}</div>
          </div>
          <el-button link size="small" :icon="Delete" class="notify-del" @click.stop="store.remove(n.id)" />
        </div>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.notify-bell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--p-text);
  cursor: pointer;
}
.notify-bell:hover {
  background: var(--p-hover, rgba(127, 127, 127, 0.15));
}
.notify-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.notify-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.notify-filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.notify-empty {
  text-align: center;
  color: var(--p-muted);
  padding: 24px 0;
  font-size: 13px;
}
.notify-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
}
.notify-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--p-card, rgba(127, 127, 127, 0.08));
}
.notify-item.unread {
  outline: 1px solid var(--el-color-primary-light-5);
}
.notify-item-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.notify-item-title {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.notify-item .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-color-info);
  flex-shrink: 0;
}
.notify-item.warn .dot { background: var(--el-color-warning); }
.notify-item.error .dot { background: var(--el-color-danger); }
.notify-item-body {
  font-size: 12px;
  color: var(--p-muted);
  margin-top: 2px;
  word-break: break-all;
}
.notify-item-meta {
  font-size: 11px;
  color: var(--p-muted);
  margin-top: 4px;
  opacity: 0.8;
}
.notify-del {
  flex-shrink: 0;
}
</style>
