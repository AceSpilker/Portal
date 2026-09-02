import request from './request'

export interface IconItem {
  id: number
  name: string
  /** builtin = Element 内置（element_name 渲染）；custom = 上传图片（path 渲染） */
  source: 'builtin' | 'custom'
  /** 内置图标的 Element 组件名（PascalCase） */
  element_name: string | null
  /** 覆盖图/自定义图的静态路径（/icons/…） */
  path: string | null
}

export interface CustomIconPayload {
  name: string
  filename?: string
  /** base64 图片内容 */
  data?: string
}

/** 图标库（内置 + 自定义统一管理，全部可编辑/删除）。 */
export const iconsApi = {
  list: () => request.get<never, IconItem[]>('/icons'),
  seed: (names: string[]) =>
    request.post<never, { seeded: number }>('/icons/seed', { names }),
  create: (payload: CustomIconPayload) => request.post<never, IconItem>('/icons', payload),
  update: (id: number, payload: Partial<CustomIconPayload>) =>
    request.put<never, IconItem>(`/icons/${id}`, payload),
  remove: (id: number) => request.delete<never, null>(`/icons/${id}`),
}
