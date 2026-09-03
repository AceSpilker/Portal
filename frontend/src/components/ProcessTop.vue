<script setup lang="ts">
/**
 * 进程 Top 榜（M17-12；dev-plan P10.1）：按 CPU/内存排序 + 名称/用户过滤。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorApi, type ProcRow } from '../api/monitor'

const { t } = useI18n()
const rows = ref<ProcRow[]>([])
const sort = ref<'cpu' | 'mem'>('cpu')
const q = ref('')
const loading = ref(false)
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    rows.value = await monitorApi.processes(sort.value, q.value, 15)
  } finally {
    loading.value = false
  }
}

function onSort(v: 'cpu' | 'mem') {
  sort.value = v
  void load()
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 5000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <section class="glass chart-card">
    <header class="proc-head">
      <h3>{{ t('monitor.procTitle') }}</h3>
      <div class="proc-tools">
        <el-input
          v-model="q"
          size="small"
          clearable
          :placeholder="t('monitor.procSearchPh')"
          style="width: 160px"
          @input="load"
        />
        <el-radio-group :model-value="sort" size="small" @update:model-value="onSort">
          <el-radio-button value="cpu">CPU</el-radio-button>
          <el-radio-button value="mem">{{ t('monitor.procByMem') }}</el-radio-button>
        </el-radio-group>
      </div>
    </header>
    <el-table :data="rows" size="small" height="260" v-loading="loading">
      <el-table-column prop="pid" label="PID" width="80" />
      <el-table-column prop="name" :label="t('monitor.procName')" min-width="160" show-overflow-tooltip />
      <el-table-column prop="username" :label="t('monitor.procUser')" min-width="100" show-overflow-tooltip />
      <el-table-column label="CPU" width="90" align="right">
        <template #default="{ row }">{{ row.cpu_percent.toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column :label="t('monitor.procMem')" width="130" align="right">
        <template #default="{ row }">{{ row.mem_percent }}% · {{ row.mem_mb }}MB</template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
.proc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.proc-head h3 {
  margin: 0;
}
.proc-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
