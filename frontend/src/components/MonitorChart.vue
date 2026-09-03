<script setup lang="ts">
/**
 * ECharts 封装（P5.5）：按需注册模块控制包体；容器尺寸自适应；卸载即销毁。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ option: echarts.EChartsCoreOption; height?: string }>()
const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

onMounted(() => {
  chart = echarts.init(el.value!)
  chart.setOption(props.option)
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value!)
})
watch(
  () => props.option,
  (opt) => chart?.setOption(opt, { notMerge: true }), // 整体替换：series 数量/名称变化时不得残留旧序列
  { deep: true },
)
onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" :style="{ height: height ?? '260px', width: '100%' }" />
</template>
