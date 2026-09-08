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
  chart.setOption({ animation: false, ...props.option })
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value!)
})
watch(
  () => props.option,
  // 浅侦听（option 每次为整体新对象）；replaceMerge:series/坐标轴——历史曲线切换指标时
  // 旧轴的 name/formatter/max 若走 merge 会残留到新图（068 实测：速率轴残留"%"轴名），
  // 坐标轴每次都整体重声明，替换合并无残留且不额外重建；关闭动画——实时图表每 2s 重绘，动画是主要卡顿来源
  (opt) => chart?.setOption({ animation: false, ...opt }, { replaceMerge: ['series', 'xAxis', 'yAxis'] }),
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
