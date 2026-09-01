import request from './request'

export interface HealthInfo {
  status: string
  app: string
  version: string
  /** 是否已初始化（存在用户）；false 时前端进入初始化向导 */
  initialized: boolean
}

/** 健康检查（公开接口，P0 联调自检用）。 */
export const getHealth = () => request.get<never, HealthInfo>('/health')
