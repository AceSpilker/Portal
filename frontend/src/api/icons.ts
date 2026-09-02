import request from './request'

export interface CustomIcon {
  id: number
  name: string
  /** /icons/<file> 静态路径 */
  path: string
}

export interface CustomIconPayload {
  name: string
  filename?: string
  /** base64 图片内容 */
  data?: string
}

/** 自定义图标管理（图标库）。 */
export const iconsApi = {
  list: () => request.get<never, CustomIcon[]>('/icons'),
  create: (payload: CustomIconPayload) => request.post<never, CustomIcon>('/icons', payload),
  update: (id: number, payload: Partial<CustomIconPayload>) =>
    request.put<never, CustomIcon>(`/icons/${id}`, payload),
  remove: (id: number) => request.delete<never, null>(`/icons/${id}`),
}
