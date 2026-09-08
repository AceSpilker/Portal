<script setup lang="ts">
/**
 * 日程与提醒面板（M13-1~5；dev-plan P16.1）。
 *
 * - el-calendar 月视图：日期单元格显示事件角标与农历节日；
 * - 点日期查看/新增当日事件；事件支持重复规则、农历生日、提醒提前分钟；
 * - 待办清单（勾选完成、按日期分组）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete as IconDelete, Plus as IconPlus } from '@element-plus/icons-vue'
import { scheduleApi, type HolidaysData, type HolidayDay } from '../api/schedule'
import type { CalendarEvent, MonthData, TodoItem } from '../api/schedule'

const { t } = useI18n()

const viewDate = ref(new Date())
const monthData = ref<MonthData | null>(null)
const loading = ref(false)

// ---- 法定节假日（077：holiday-cn 数据集动态获取，含调休班日） ----
const holidays = ref<HolidaysData | null>(null)
const holidayMap = computed(() => {
  const m = new Map<string, HolidayDay>()
  for (const d of holidays.value?.days ?? []) m.set(d.date, d)
  return m
})
function holidayOn(cell: Date): HolidayDay | undefined {
  return holidayMap.value.get(ymd(cell))
}

// ---- 事件弹窗 ----
const dlg = ref(false)
const editing = ref<CalendarEvent | null>(null)
const selDate = ref('')
const form = ref({
  title: '',
  note: '',
  time: '' as string | '',
  repeat: 'none',
  interval_days: 1,
  lunar: false,
  remind_minutes: 0,
})

// ---- 当日列表 ----
const dayEvents = computed(() =>
  (monthData.value?.events ?? []).filter((e) => e.date === ymd(viewDate.value)),
)

function ymd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function load() {
  loading.value = true
  try {
    const d = viewDate.value
    monthData.value = await scheduleApi.month(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
  await ensureHolidays(viewDate.value.getFullYear())
}

async function ensureHolidays(year: number) {
  if (holidays.value?.year === year) return
  try {
    holidays.value = await scheduleApi.holidays(year)
  } catch (e) {
    console.warn('[schedule] 节假日获取失败', e)
  }
}

watch(viewDate, load)
watch(
  () => viewDate.value.getFullYear(),
  (y) => void ensureHolidays(y),
  { immediate: true },
)
onMounted(load)

function eventsOn(cell: Date) {
  const key = ymd(cell)
  return (monthData.value?.events ?? []).filter((e) => e.date === key)
}

function festivalsOn(cell: Date) {
  const key = ymd(cell)
  return (monthData.value?.festivals ?? []).filter((f) => f.date === key)
}

function openDay(cell: Date) {
  selDate.value = ymd(cell)
  editing.value = null
  form.value = { title: '', note: '', time: '', repeat: 'none', interval_days: 1, lunar: false, remind_minutes: 0 }
  dlg.value = true
}

function openEdit(e: CalendarEvent & { date: string }) {
  editing.value = e
  selDate.value = e.date
  form.value = {
    title: e.title,
    note: e.note,
    time: e.time ?? '',
    repeat: e.repeat,
    interval_days: e.interval_days,
    lunar: e.lunar,
    remind_minutes: e.remind_minutes,
  }
  dlg.value = true
}

async function saveEvent() {
  if (!form.value.title.trim()) {
    ElMessage.warning(t('eff.eventTitleRequired'))
    return
  }
  const body = {
    title: form.value.title.trim(),
    note: form.value.note,
    date: selDate.value,
    time: form.value.time || null,
    repeat: form.value.lunar ? 'yearly' : form.value.repeat,
    interval_days: form.value.interval_days,
    lunar: form.value.lunar,
    remind_minutes: form.value.remind_minutes,
  }
  try {
    if (editing.value) {
      await scheduleApi.updateEvent(editing.value.id, body)
    } else {
      await scheduleApi.createEvent(body)
    }
    dlg.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeEvent(e: { id: number; title: string }) {
  try {
    await ElMessageBox.confirm(t('eff.eventDeleteConfirm', { name: e.title }), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await scheduleApi.deleteEvent(e.id)
    dlg.value = false
    await load()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

// ---- 待办 ----
const todos = ref<TodoItem[]>([])
const newTodo = ref('')

async function loadTodos() {
  try {
    todos.value = await scheduleApi.listTodos()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function addTodo() {
  const title = newTodo.value.trim()
  if (!title) return
  try {
    // 待办绑定当前选中日期（077：原固定今天，用户不知绑定关系）
    await scheduleApi.createTodo(title, ymd(viewDate.value))
    newTodo.value = ''
    await loadTodos()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function toggleTodo(td: TodoItem) {
  try {
    await scheduleApi.updateTodo(td.id, { title: td.title, done: !td.done, date: td.date })
    td.done = !td.done
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeTodo(td: TodoItem) {
  try {
    await scheduleApi.deleteTodo(td.id)
    todos.value = todos.value.filter((x) => x.id !== td.id)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

/** 当日覆盖的待办数（开始~结束区间内，077 用户需求：区间内在日历显示） */
function todosOn(day: Date): number {
  const key = ymd(day)
  return todos.value.filter((td) => {
    const start = td.date ?? '0000-01-01'
    const end = td.end_date ?? td.date ?? start
    return start <= key && key <= end
  }).length
}

// ---- 待办编辑（077：区间待办） ----
const todoDlg = ref(false)
const editingTodo = ref<TodoItem | null>(null)
const todoForm = ref({ title: '', range: [] as string[], done: false })

function openTodoEdit(td: TodoItem) {
  editingTodo.value = td
  todoForm.value = {
    title: td.title,
    range: td.date ? [td.date, td.end_date ?? td.date] : [],
    done: td.done,
  }
  todoDlg.value = true
}

async function saveTodoEdit() {
  const td = editingTodo.value
  if (!td) return
  const [start, end] = todoForm.value.range ?? []
  try {
    await scheduleApi.updateTodo(td.id, {
      title: todoForm.value.title,
      done: todoForm.value.done,
      date: start ?? null,
      end_date: end ?? null,
    })
    todoDlg.value = false
    await loadTodos()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

const openTodos = computed(() => todos.value.filter((x) => !x.done))
const doneTodos = computed(() => todos.value.filter((x) => x.done))

onMounted(loadTodos)

const REPEATS = ['none', 'daily', 'weekly', 'monthly', 'yearly', 'custom']
</script>

<template>
  <div v-loading="loading" class="schedule">
    <div v-if="holidays?.summary?.length" class="holiday-strip glass">
      <span class="hol-title">{{ t('eff.holidaySummary') }}</span>
      <div v-for="h in holidays.summary" :key="h.name" class="hol-chip">
        <b>{{ h.name }}</b>
        <span v-for="r in h.rest_ranges" :key="r.start">
          {{ r.start.slice(5) }}~{{ r.end.slice(5) }} {{ t('eff.restDays', { n: r.days }) }}
        </span>
        <span v-if="h.makeup_dates.length" class="hol-makeup">
          {{ t('eff.makeUp') }}{{ h.makeup_dates.join('、') }}
        </span>
      </div>
    </div>

    <div class="cal-wrap glass">
      <el-calendar v-model="viewDate">
        <template #date-cell="{ data }">
          <div class="cell" @click="openDay(data.date)">
            <span class="cell-day">{{ data.date.getDate() }}</span>
            <span class="cell-dots">
              <i v-for="e in eventsOn(data.date).slice(0, 3)" :key="e.id + e.date" class="dot" :title="e.title" />
            </span>
            <span v-if="todosOn(data.date)" class="cell-todo" :title="t('eff.todos')">
              ☑ {{ todosOn(data.date) }}
            </span>
            <span v-for="f in festivalsOn(data.date)" :key="f.name" class="cell-fest">{{ f.name }}</span>
            <span v-if="holidayOn(data.date)?.isOffDay" class="cell-off">休</span>
            <span v-else-if="holidayOn(data.date)" class="cell-work">班</span>
          </div>
        </template>
      </el-calendar>
    </div>

    <div class="side">
      <section class="glass day-card">
        <header class="side-head">
          <h3>{{ selDate || ymd(viewDate) }}</h3>
          <el-button size="small" type="primary" class="btn-gradient" :icon="IconPlus" @click="openDay(viewDate)">
            {{ t('eff.addEvent') }}
          </el-button>
        </header>
        <ul class="day-list">
          <li v-for="e in dayEvents" :key="e.id + e.date" class="day-item" @click="openEdit(e)">
            <span class="ev-time">{{ e.time ?? t('eff.allDay') }}</span>
            <span class="ev-title">{{ e.title }}</span>
            <el-tag v-if="e.lunar" size="small" type="warning">{{ t('eff.lunar') }}</el-tag>
            <el-tag v-if="e.repeat !== 'none'" size="small" type="info">{{ t(`eff.repeat.${e.repeat}`) }}</el-tag>
          </li>
          <li v-if="!dayEvents.length" class="day-empty">{{ t('common.noData') }}</li>
        </ul>
      </section>

      <section class="glass day-card">
        <header class="side-head">
          <h3>{{ t('eff.todos') }}</h3>
          <span class="todo-count">{{ openTodos.length }}</span>
        </header>
        <div class="todo-add">
          <el-input
            v-model="newTodo"
            :placeholder="t('eff.todoPlaceholder')"
            size="small"
            @keyup.enter="addTodo"
          />
          <el-button size="small" :icon="IconPlus" @click="addTodo" />
        </div>
        <ul class="day-list">
          <li v-for="td in openTodos" :key="td.id" class="day-item todo">
            <el-checkbox :model-value="false" @change="toggleTodo(td)" />
            <span class="ev-title todo-title" :title="t('common.edit')" @click="openTodoEdit(td)">{{ td.title }}</span>
            <span v-if="td.date" class="todo-range">{{ td.end_date ? `${td.date.slice(5)}~${td.end_date.slice(5)}` : td.date.slice(5) }}</span>
            <el-button link size="small" :icon="IconDelete" class="todo-del" @click="removeTodo(td)" />
          </li>
          <li v-for="td in doneTodos" :key="td.id" class="day-item todo done">
            <el-checkbox :model-value="true" @change="toggleTodo(td)" />
            <span class="ev-title todo-title" :title="t('common.edit')" @click="openTodoEdit(td)">{{ td.title }}</span>
            <span v-if="td.date" class="todo-range">{{ td.end_date ? `${td.date.slice(5)}~${td.end_date.slice(5)}` : td.date.slice(5) }}</span>
            <el-button link size="small" :icon="IconDelete" class="todo-del" @click="removeTodo(td)" />
          </li>
        </ul>
      </section>
    </div>

    <!-- 待办编辑（077：区间待办） -->
    <el-dialog v-model="todoDlg" :title="t('eff.todoEdit')" width="420px" append-to-body>
      <el-form label-width="72px" label-position="left">
        <el-form-item :label="t('eff.eventTitle')">
          <el-input v-model="todoForm.title" maxlength="128" />
        </el-form-item>
        <el-form-item :label="t('eff.todoRange')">
          <el-date-picker
            v-model="todoForm.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 100%"
            clearable
          />
        </el-form-item>
        <el-form-item :label="t('eff.done')">
          <el-switch v-model="todoForm.done" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="todoDlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveTodoEdit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg" :title="editing ? t('eff.editEvent') : t('eff.addEvent')" width="440px" append-to-body>
      <el-form label-width="72px" label-position="left">
        <el-form-item :label="t('eff.eventTitle')">
          <el-input v-model="form.title" maxlength="128" />
        </el-form-item>
        <el-form-item :label="t('eff.eventDate')">
          <el-input :model-value="selDate" disabled />
        </el-form-item>
        <el-form-item :label="t('eff.eventTime')">
          <el-time-select v-model="form.time" start="00:00" step="00:15" end="23:45" :placeholder="t('eff.allDay')" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('eff.eventRepeat')">
          <el-select v-model="form.repeat" :disabled="form.lunar" style="width: 100%">
            <el-option v-for="r in REPEATS" :key="r" :value="r" :label="t(`eff.repeat.${r}`)" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.repeat === 'custom'">
          <el-input-number v-model="form.interval_days" :min="1" :max="3650" />
          <span class="form-tip">{{ t('eff.intervalDays') }}</span>
        </el-form-item>
        <el-form-item :label="t('eff.lunar')">
          <el-switch v-model="form.lunar" />
          <span class="form-tip">{{ t('eff.lunarTip') }}</span>
        </el-form-item>
        <el-form-item :label="t('eff.remind')">
          <el-select v-model="form.remind_minutes" style="width: 100%">
            <el-option :value="0" :label="t('eff.remindAt')" />
            <el-option :value="5" :label="t('eff.remindBefore', { n: 5 })" />
            <el-option :value="15" :label="t('eff.remindBefore', { n: 15 })" />
            <el-option :value="30" :label="t('eff.remindBefore', { n: 30 })" />
            <el-option :value="60" :label="t('eff.remindBefore', { n: 60 })" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('eff.eventNote')">
          <el-input v-model="form.note" type="textarea" :rows="2" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="editing" type="danger" plain @click="removeEvent(editing)">{{ t('common.delete') }}</el-button>
        <el-button @click="dlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveEvent">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.schedule {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 12px;
  align-items: start;
}
.cal-wrap {
  padding: 8px;
}
.cell {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 52px;
  cursor: pointer;
}
.cell-day {
  font-size: 13px;
}
.cell-dots {
  display: flex;
  gap: 3px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--p-primary);
}
.cell-fest {
  font-size: 10.5px;
  color: #e0566a;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.day-card {
  padding: 12px 14px;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.side-head h3 {
  margin: 0;
  font-size: 14px;
}
.todo-count {
  font-size: 12px;
  color: var(--p-muted);
}
.day-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}
.day-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--p-primary) 4%, transparent);
  cursor: pointer;
  font-size: 13px;
}
.ev-time {
  font-size: 11.5px;
  color: var(--p-muted);
  flex-shrink: 0;
}
.ev-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.day-empty {
  color: var(--p-muted);
  font-size: 12.5px;
  text-align: center;
  padding: 10px 0;
}
.todo-add {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.todo.done .ev-title {
  text-decoration: line-through;
  color: var(--p-muted);
}
.todo-del {
  opacity: 0.5;
}
.todo-del:hover {
  opacity: 1;
}
.form-tip {
  margin-left: 8px;
  font-size: 12px;
  color: var(--p-muted);
}
@media (max-width: 1000px) {
  .schedule {
    grid-template-columns: 1fr;
  }
}
.holiday-strip {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.hol-title {
  font-size: 13px;
  font-weight: 600;
}
.hol-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--p-muted);
  background: var(--p-card, rgba(255, 255, 255, 0.04));
  border-radius: 8px;
  padding: 4px 10px;
}
.hol-chip b {
  color: var(--p-text);
}
.hol-makeup {
  color: var(--el-color-warning);
}
.cell-off,
.cell-work {
  position: absolute;
  top: 2px;
  right: 4px;
  font-size: 10px;
  line-height: 1;
  padding: 1px 3px;
  border-radius: 4px;
}
.cell-off {
  color: var(--el-color-danger);
  border: 1px solid var(--el-color-danger);
}
.cell-work {
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary);
}
</style>

<!-- 077r2 cache-bust -->
