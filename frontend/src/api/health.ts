import request from './request'

export interface HealthInfo {
  status: string
  app: string
  version: string
}

/** 健康检查（公开接口，P0 联调自检用）。 */
export const getHealth = () => request.get<never, HealthInfo>('/health')
