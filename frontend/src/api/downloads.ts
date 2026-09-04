import request from './request'

/** 下载与媒体（M12；dev-plan P16.3；api-spec §4.11）。 */

export interface DownloadsSummary {
  enabled: boolean
  connected: boolean
  error?: string
  counts: Partial<Record<'downloading' | 'completed' | 'paused' | 'seeding' | 'error', number>>
  speed: { dl: number; up: number }
}

export interface TorrentTask {
  hash: string
  name: string
  size: number
  progress: number
  state: string
  completed: boolean
  dlspeed: number
  upspeed: number
  num_seeds?: number
  num_leechs?: number
  eta?: number
  category: string
}

export interface MediaItem {
  id: string
  title: string
  series: string
  added_at: string
  poster: string | null
}

export const downloadsApi = {
  summary: () => request.get<never, DownloadsSummary>('/downloads/summary'),
  tasks: () => request.get<never, TorrentTask[]>('/downloads/tasks'),
  add: (urls: string[]) =>
    request.post<never, { count: number }>('/downloads/tasks', { urls }),
  mediaRecent: () => request.get<never, { items: MediaItem[] }>('/media/recent'),
}
