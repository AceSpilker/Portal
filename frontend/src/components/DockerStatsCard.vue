<script setup lang="ts">
/**
 * Docker 资源占用（M17-13；dev-plan P10.2）：无 docker.sock 时后端返回空数组，卡片隐藏。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorApi, type DockerStat } from '../api/monitor'

const { t } = useI18n()
const rows = ref<DockerStat[] | null>(null)

onMounted(async () => {
  try {
    rows.value = await monitorApi.dockerStats()
  } catch {
    rows.value = []
  }
})
</script>

<template>
  <section v-if="rows && rows.length" class="glass chart-card">
    <h3>{{ t('monitor.dockerTitle') }}</h3>
    <el-table :data="rows" size="small">
      <el-table-column prop="name" :label="t('monitor.dockerName')" min-width="140" show-overflow-tooltip />
      <el-table-column prop="image" :label="t('monitor.dockerImage')" min-width="150" show-overflow-tooltip />
      <el-table-column label="CPU" width="80" align="right">
        <template #default="{ row }">{{ row.cpu_percent }}%</template>
      </el-table-column>
      <el-table-column :label="t('monitor.dockerMem')" width="150" align="right">
        <template #default="{ row }">
          {{ row.mem_used_mb }}MB · {{ row.mem_percent }}%
        </template>
      </el-table-column>
      <el-table-column :label="t('monitor.dockerNet')" width="140" align="right">
        <template #default="{ row }">↓{{ row.net_rx_mb }} / ↑{{ row.net_tx_mb }}MB</template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
h3 {
  margin: 0 0 8px;
}
</style>
