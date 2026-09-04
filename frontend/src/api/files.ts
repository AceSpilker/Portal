import request from './request'

/** 文件管理（M11；dev-plan P16.2；api-spec §4.11）。 */

export interface FileEntry {
  name: string
  dir: boolean
  size: number
  mtime: string
}

export interface DirListing {
  root: string
  path: string
  entries: FileEntry[]
}

export interface FileRoot {
  name: string
  path: string
}

export const filesApi = {
  roots: () => request.get<never, FileRoot[]>('/files/roots'),
  list: (root: string, path = '') =>
    request.get<never, DirListing>('/files/list', { params: { root, path } }),
  upload: (root: string, path: string, filename: string, data: string) =>
    request.post<never, { path: string; size: number }>('/files/upload', {
      root,
      path,
      filename,
      data,
    }),
  download: (root: string, path: string) =>
    request.get<never, { filename: string; size: number; data: string }>('/files/download', {
      params: { root, path },
    }),
  mkdir: (root: string, path: string, name: string) =>
    request.post<never, { path: string }>('/files/mkdir', { root, path, name }),
  rename: (root: string, path: string, name: string) =>
    request.post<never, { path: string }>('/files/rename', { root, path, name }),
  remove: (root: string, path: string) =>
    request.post<never, { deleted: string }>('/files/delete', { root, path }),
  move: (root: string, path: string, dest: string) =>
    request.post<never, { path: string }>('/files/move', { root, path, dest }),
  rawUrl: (root: string, path: string) =>
    request.post<never, { url: string; expires_in: number }>('/files/raw-url', { root, path }),
}
