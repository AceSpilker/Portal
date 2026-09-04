import request from './request'

/** 日程与待办（M13；dev-plan P16.1；api-spec §4.11）。 */

export interface CalendarEvent {
  id: number
  title: string
  note: string
  date: string
  time: string | null
  repeat: string
  interval_days: number
  lunar: boolean
  remind_minutes: number
}

export interface MonthData {
  ym: string
  events: Array<CalendarEvent & { date: string }>
  festivals: Array<{ date: string; name: string }>
}

export interface TodoItem {
  id: number
  title: string
  done: boolean
  date: string | null
  sort: number
}

export interface EventBody {
  title: string
  note?: string
  date: string
  time?: string | null
  repeat?: string
  interval_days?: number
  lunar?: boolean
  remind_minutes?: number
}

export const scheduleApi = {
  month: (ym: string) =>
    request.get<never, MonthData>('/calendar/month', { params: { ym } }),
  createEvent: (body: EventBody) => request.post<never, CalendarEvent>('/calendar/events', body),
  updateEvent: (id: number, body: EventBody) =>
    request.put<never, CalendarEvent>(`/calendar/events/${id}`, body),
  deleteEvent: (id: number) => request.delete<never, { id: number }>(`/calendar/events/${id}`),
  listTodos: () => request.get<never, TodoItem[]>('/todos'),
  createTodo: (title: string, date?: string | null) =>
    request.post<never, TodoItem>('/todos', { title, date: date ?? null }),
  updateTodo: (id: number, body: { title: string; done: boolean; date?: string | null }) =>
    request.put<never, TodoItem>(`/todos/${id}`, body),
  deleteTodo: (id: number) => request.delete<never, { id: number }>(`/todos/${id}`),
}
