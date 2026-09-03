import request from './request'

/** 首页仪表盘布局（M02-2/M02-5；api-spec §3.2 dashboard_layouts / §4.13）。 */
export interface LayoutItem {
  tab: string
  sort: number
  layout: Record<string, unknown>
}

export interface TabItem {
  tab: string
  title: string
  sort: number
}

export const layoutApi = {
  getMyLayouts: () => request.get<never, LayoutItem[]>('/me/layouts'),
  saveMyLayout: (tab: string, layout: Record<string, unknown>) =>
    request.put<never, { tab: string; layout: Record<string, unknown> }>('/me/layouts', {
      tab,
      layout,
    }),
  // 多标签页（P15.2/M02-5）
  getMyTabs: () => request.get<never, TabItem[]>('/me/tabs'),
  createTab: (title: string) => request.post<never, TabItem>('/me/tabs', { title }),
  updateTabs: (items: TabItem[]) => request.put<never, TabItem[]>('/me/tabs', { items }),
  deleteTab: (tab: string) => request.delete<never, { tab: string }>(`/me/tabs/${tab}`),
}
