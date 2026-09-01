import { useMediaQuery } from '@vueuse/core'

/**
 * 移动端判定（<768px）。
 * 模块级共享单一 ref，所有组件引用同一状态，避免重复监听。
 *
 * 断点体系（与 styles/index.css 一致）：
 *   <768px   移动端（底部 Tab 导航、单列布局）
 *   768~1079 平板（收窄侧边栏）
 *   ≥1080    桌面（完整侧边栏）
 */
export const isMobile = useMediaQuery('(max-width: 767px)')
export const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1079px)')

export function useIsMobile() {
  return { isMobile, isTablet }
}
