<script setup lang="ts">
/**
 * 审计日志页（M01-14/M15-13；dev-plan P17.1；087 执行详情增强）：
 * 筛选（时间/动作/方法）/分页/CSV 导出；方法与接口分列显示，
 * 行展开看完整执行详情（UA/查询串/错误消息）。
 * 旧记录（087 前）method/path 为空——展示时从 action "METHOD path" 解析兜底。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Download as IconDownload, Refresh as IconRefresh } from '@element-plus/icons-vue'
import { settingsApi, type AuditItem } from '../api/settings'

const { t } = useI18n()
const items = ref<AuditItem[]>([])
const total = ref(0)
const page = ref(1)
const range = ref('7d')
const actionFilter = ref('')
const methodFilter = ref('')
const loading = ref(false)

const METHOD_TAGS: Record<string, 'primary' | 'warning' | 'danger' | 'success' | 'info'> = {
  POST: 'primary',
  PUT: 'warning',
  PATCH: 'warning',
  DELETE: 'danger',
  GET: 'success',
}

async function load() {
  loading.value = true
  try {
    const r = await settingsApi.auditLogs({
      range: range.value,
      action: actionFilter.value,
      method: methodFilter.value,
      page: page.value,
    })
    items.value = r.items
    total.value = r.total
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  try {
    const r = await settingsApi.auditExport(range.value)
    // created_at 列（ISO-UTC）转本地时间后再导出
    const csv = r.csv.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?/g, (m) => toLocalIso(m))
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = r.filename
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

/** 旧记录兜底：从 action "POST /api/apps" 解析方法与路径（087 前无拆列） */
function splitAction(row: AuditItem): { method: string; path: string } {
  if (row.method || row.path) return { method: row.method, path: row.path }
  const sp = row.action.split(' ')
  return sp.length >= 2 ? { method: sp[0], path: sp.slice(1).join(' ') } : { method: '', path: row.action }
}
const methodOf = (row: AuditItem) => splitAction(row).method
const pathOf = (row: AuditItem) => splitAction(row).path

/** 业务动作摘要：手动审计（login 等）显示 action 语义；自动审计与接口列重复则不重复展示 */
const bizActionOf = (row: AuditItem) => (row.path ? '' : row.action)

const statusType = (s: number): 'success' | 'warning' | 'danger' | 'info' =>
  s >= 500 ? 'danger' : s >= 400 ? 'warning' : s >= 200 && s < 300 ? 'success' : 'info'

/** ISO-UTC → 本地时间显示（DB 约定存 UTC，显示层统一转换；073 用户反馈） */
function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

/** CSV 导出用：本地 ISO 格式（2026-09-08 16:09:36） */
function toLocalIso(v: string): string {
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString('sv-SE', { hour12: false })
}

const userLabel = (row: AuditItem) => row.username || (row.user_id !== null ? `#${row.user_id}` : '-')

onMounted(load)
</script>

<template>
  <div class="audit">
    <header class="bar glass">
      <el-select v-model="range" size="small" style="width: 110px" @change="page = 1; load()">
        <el-option value="24h" :label="t('security.range24h')" />
        <el-option value="7d" :label="t('security.range7d')" />
        <el-option value="30d" :label="t('security.range30d')" />
        <el-option value="all" :label="t('security.rangeAll')" />
      </el-select>
      <el-select
        v-model="methodFilter"
        size="small"
        style="width: 118px"
        clearable
        :placeholder="t('security.methodPh')"
        @change="page = 1; load()"
      >
        <el-option value="POST" label="POST" />
        <el-option value="PUT" label="PUT" />
        <el-option value="PATCH" label="PATCH" />
        <el-option value="DELETE" label="DELETE" />
      </el-select>
      <el-input
        v-model="actionFilter"
        size="small"
        :placeholder="t('security.actionPh')"
        style="width: 180px"
        clearable
        @keyup.enter="page = 1; load()"
      />
      <el-button size="small" :icon="IconRefresh" circle @click="load" />
      <span class="spacer" />
      <el-button size="small" :icon="IconDownload" @click="exportCsv">{{ t('security.exportCsv') }}</el-button>
    </header>

    <section class="glass table-card" v-loading="loading">
      <div class="table-fill">
        <el-table :data="items" height="100%" size="small" style="width: 100%">
          <!-- 展开行：完整执行详情（087） -->
          <el-table-column type="expand" width="34">
            <template #default="{ row }">
              <div class="expand-body">
                <div class="ex-row">
                  <span class="ex-k">{{ t('security.colStatus') }}</span>
                  <el-tag size="small" :type="statusType(row.status)" effect="plain">{{ row.status || '-' }}</el-tag>
                  <span class="ex-k">{{ t('security.colDuration') }}</span>
                  <span>{{ row.duration_ms ? `${row.duration_ms}ms` : t('security.detailNone') }}</span>
                  <span class="ex-k">{{ t('security.detailQuery') }}</span>
                  <span class="ex-mono">{{ row.query || t('security.detailNone') }}</span>
                </div>
                <div class="ex-row">
                  <span class="ex-k">{{ t('security.detailError') }}</span>
                  <span :class="{ 'ex-err': row.error_msg }">{{ row.error_msg || t('security.detailNone') }}</span>
                </div>
                <div class="ex-row">
                  <span class="ex-k">{{ t('security.detailUA') }}</span>
                  <span class="ex-mono">{{ row.user_agent || t('security.detailNone') }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('security.colTime')" width="158">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('security.colMethod')" width="90">
            <template #default="{ row }">
              <el-tag
                v-if="methodOf(row)"
                size="small"
                :type="METHOD_TAGS[methodOf(row)] ?? 'info'"
                effect="light"
                class="method-tag"
              >{{ methodOf(row) }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('security.colPath')" min-width="200">
            <template #default="{ row }">
              <span class="path-cell" :title="pathOf(row)">{{ pathOf(row) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('security.colDetail')" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <!-- 手动业务审计显示动作语义；自动审计展示错误消息或人读摘要 -->
              <span v-if="bizActionOf(row)">{{ bizActionOf(row) }}</span>
              <span v-else-if="row.error_msg" class="err-text">{{ row.error_msg }}</span>
              <span v-else class="muted-cell">{{ row.detail }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('security.colStatus')" width="74" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.status" size="small" :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('security.colDuration')" width="80" align="right">
            <template #default="{ row }">{{ row.duration_ms ? `${row.duration_ms}ms` : '-' }}</template>
          </el-table-column>
          <el-table-column :label="t('security.colUser')" width="112" show-overflow-tooltip>
            <template #default="{ row }">{{ userLabel(row) }}</template>
          </el-table-column>
          <el-table-column prop="ip" :label="t('security.colIp')" width="122" show-overflow-tooltip />
        </el-table>
      </div>
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="50"
        :total="total"
        class="pager"
        @current-change="load"
      />
    </section>
  </div>
</template>

<style scoped>
.audit {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bar {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 8px 14px;
}
.spacer {
  flex: 1;
}
.table-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 6px 10px 10px;
}
.table-fill {
  flex: 1;
  min-height: 0;
}
.pager {
  flex-shrink: 0;
  margin-top: 10px;
  justify-content: flex-end;
}
.method-tag {
  font-family: ui-monospace, monospace;
  min-width: 58px;
  justify-content: center;
}
.path-cell {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.err-text {
  color: var(--el-color-danger);
}
.muted-cell {
  color: var(--p-muted);
}
.expand-body {
  padding: 4px 12px 8px 40px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ex-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 12.5px;
  align-items: baseline;
}
.ex-k {
  color: var(--p-muted);
  flex-shrink: 0;
}
.ex-k::after {
  content: ':';
}
.ex-mono {
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
.ex-err {
  color: var(--el-color-danger);
}
</style>
