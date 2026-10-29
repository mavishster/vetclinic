<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none">График работы</h1>
      <q-space />
      <q-btn flat round icon="chevron_left" @click="shiftWeek(-1)" />
      <div class="text-subtitle1 text-weight-medium">{{ weekTitle }}</div>
      <q-btn flat round icon="chevron_right" @click="shiftWeek(1)" />
      <q-btn flat no-caps label="Текущая неделя" @click="goToday" />
    </div>

    <div v-if="canAdd" class="row q-col-gutter-sm items-center q-mb-md">
      <q-select v-model="fillTemplate" :options="templates" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Заполнять по шаблону" class="col-12 col-sm-4"
        hint="Выберите шаблон и нажимайте на клетки — интервал добавится сразу" />
      <div class="col-auto">
        <q-btn outline color="primary" icon="content_copy" label="Скопировать неделю на следующую" @click="copyWeek" />
      </div>
    </div>

    <div class="schedule-scroll">
      <table class="schedule">
        <thead>
          <tr>
            <th class="employee-col">Сотрудник</th>
            <th v-for="day in days" :key="day.iso" :class="{ today: day.iso === todayIso, weekend: day.weekend }">
              {{ day.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="employee in employees" :key="employee.id">
            <td class="employee-col">
              <q-icon name="circle" :style="{ color: employee.color }" size="10px" class="q-mr-xs" />
              {{ employee.full_name || employee.username }}
              <div class="text-caption text-grey-7">{{ employee.position_name }}</div>
            </td>
            <td v-for="day in days" :key="day.iso" class="cell" :class="{ today: day.iso === todayIso, clickable: canAdd }"
              @click="onCell(employee, day)">
              <div v-for="item in cellIntervals(employee, day)" :key="item.id" class="chip"
                :style="{ background: item.type_color }" @click.stop="openInterval(item)">
                {{ chipText(item, day) }}
                <q-tooltip>{{ item.type_name }}{{ item.comment ? ` · ${item.comment}` : '' }}</q-tooltip>
              </div>
            </td>
          </tr>
          <tr v-if="!employees.length">
            <td :colspan="8" class="text-grey-7 q-pa-md">
              Нет сотрудников для графика. Добавьте их в «Сотрудники» и отметьте «В графике».
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <q-dialog v-model="editorOpen">
      <q-card style="width: 460px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ form.id ? 'Интервал' : 'Новый интервал' }} · {{ employeeName(form.user) }}</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <q-select v-if="!form.id" v-model="dialogTemplate" :options="templates" option-value="id" option-label="name"
              emit-value map-options dense outlined clearable label="Шаблон" @update:model-value="applyTemplate" />
            <q-select v-model="form.interval_type" :options="types" option-value="id" option-label="name" emit-value
              map-options dense outlined label="Тип" />
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.startDate" type="date" label="С" stack-label dense outlined class="col-7" />
              <q-input v-model="form.startTime" type="time" label="время" stack-label dense outlined class="col-5" />
              <q-input v-model="form.endDate" type="date" label="По" stack-label dense outlined class="col-7" />
              <q-input v-model="form.endTime" type="time" label="время" stack-label dense outlined class="col-5" />
            </div>
            <q-input v-model="form.comment" label="Комментарий" dense outlined />
            <div v-if="error" class="text-negative">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-if="form.id && can('staff.delete_workinterval')" flat color="negative" label="Удалить" class="q-mr-auto"
              @click="remove" />
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn v-if="form.id ? can('staff.change_workinterval') : canAdd" type="submit" color="primary" unelevated
              label="Сохранить" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const $q = useQuasar()
const canAdd = can('staff.add_workinterval')
const pad = (n) => String(n).padStart(2, '0')
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const timeOf = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
const todayIso = isoDate(new Date())

function mondayOf(date) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return d
}
const weekStart = ref(mondayOf(new Date()))
const days = computed(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    const weekday = d.toLocaleDateString('ru-RU', { weekday: 'short' })
    return { date: d, iso: isoDate(d), label: `${weekday} ${pad(d.getDate())}.${pad(d.getMonth() + 1)}`, weekend: i >= 5 }
  }),
)
const weekTitle = computed(() => `${days.value[0].label} — ${days.value[6].label}`)

const employees = ref([])
const intervals = ref([])
const templates = ref([])
const types = ref([])
const fillTemplate = ref(null)

async function load() {
  const from = days.value[0].iso
  const to = days.value[6].iso
  intervals.value = (await apiGet(`staff/intervals/?from=${from}&to=${to}`)).data ?? []
}

function shiftWeek(step) {
  const d = new Date(weekStart.value)
  d.setDate(d.getDate() + step * 7)
  weekStart.value = d
  load()
}
function goToday() {
  weekStart.value = mondayOf(new Date())
  load()
}

// Интервал показывается в каждом дне, который он задевает (ночная смена, отпуск).
function cellIntervals(employee, day) {
  const dayStart = new Date(day.date)
  const dayEnd = new Date(day.date)
  dayEnd.setDate(dayEnd.getDate() + 1)
  return intervals.value.filter(
    (i) => i.user === employee.user_id && new Date(i.start) < dayEnd && new Date(i.end) > dayStart,
  )
}
function chipText(item, day) {
  const start = new Date(item.start)
  const end = new Date(item.end)
  if (!item.is_working && end - start > 86400000) return item.type_name
  if (isoDate(start) !== day.iso) return `→ ${timeOf(end)}`
  return `${timeOf(start)}–${timeOf(end)}`
}
const employeeName = (userId) => {
  const e = employees.value.find((x) => x.user_id === userId)
  return e ? e.full_name || e.username : ''
}

// --- добавление и изменение ---
const editorOpen = ref(false)
const form = ref({})
const dialogTemplate = ref(null)
const error = ref('')

async function onCell(employee, day) {
  if (!canAdd) return
  if (fillTemplate.value) {
    const { ok, data } = await apiPost('staff/intervals/fill/', { users: [employee.user_id], days: [day.iso], template: fillTemplate.value })
    if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось' })
    if (data.skipped.length) $q.notify({ type: 'warning', message: data.skipped[0] })
    return load()
  }
  error.value = ''
  dialogTemplate.value = null
  form.value = {
    user: employee.user_id, interval_type: types.value.find((t) => t.is_working)?.id ?? null,
    startDate: day.iso, startTime: '09:00', endDate: day.iso, endTime: '21:00', comment: '',
  }
  editorOpen.value = true
}

function openInterval(item) {
  error.value = ''
  const start = new Date(item.start)
  const end = new Date(item.end)
  form.value = {
    id: item.id, user: item.user, interval_type: item.interval_type, comment: item.comment,
    startDate: isoDate(start), startTime: timeOf(start), endDate: isoDate(end), endTime: timeOf(end),
  }
  editorOpen.value = true
}

function applyTemplate(id) {
  const template = templates.value.find((t) => t.id === id)
  if (!template) return
  form.value.interval_type = template.interval_type
  form.value.startTime = template.start_time.slice(0, 5)
  form.value.endTime = template.end_time.slice(0, 5)
  const end = new Date(`${form.value.startDate}T00:00`)
  if (template.end_time <= template.start_time) end.setDate(end.getDate() + 1)
  form.value.endDate = isoDate(end)
}

async function save() {
  error.value = ''
  // Время вводится по часам этого компьютера и отправляется с часовым поясом —
  // сервер сохранит тот же момент, даже если его часовой пояс другой.
  const moment = (day, time) => new Date(`${day}T${time}`).toISOString()
  const body = {
    user: form.value.user, interval_type: form.value.interval_type, comment: form.value.comment,
    start: moment(form.value.startDate, form.value.startTime), end: moment(form.value.endDate, form.value.endTime),
  }
  const { ok, data } = form.value.id
    ? await apiPatch(`staff/intervals/${form.value.id}/`, body)
    : await apiPost('staff/intervals/', body)
  if (!ok) {
    error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить'
    return
  }
  editorOpen.value = false
  load()
}

async function remove() {
  const { ok } = await apiDelete(`staff/intervals/${form.value.id}/`)
  if (ok) {
    editorOpen.value = false
    load()
  }
}

function copyWeek() {
  const next = new Date(weekStart.value)
  next.setDate(next.getDate() + 7)
  $q.dialog({
    title: 'Скопировать график?',
    message: `Интервалы этой недели будут добавлены на неделю с ${next.toLocaleDateString('ru-RU')}. Пересечения пропустятся.`,
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Скопировать', color: 'primary', unelevated: true },
  }).onOk(async () => {
    const { ok, data } = await apiPost('staff/intervals/copy-week/', { from: isoDate(weekStart.value), to: isoDate(next) })
    if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось скопировать' })
    $q.notify({
      type: data.skipped.length ? 'warning' : 'positive',
      message: `Скопировано: ${data.created}${data.skipped.length ? `, пропущено: ${data.skipped.length}` : ''}`,
    })
    shiftWeek(1)
  })
}

onMounted(async () => {
  const [e, t, ty] = await Promise.all([
    apiGet('staff/employees/?schedule=true'),
    apiGet('staff/templates/?active=true'),
    apiGet('staff/interval-types/?active=true'),
  ])
  employees.value = e.data ?? []
  templates.value = t.data ?? []
  types.value = ty.data ?? []
  load()
})
</script>

<style scoped>
.schedule-scroll {
  overflow-x: auto;
}
.schedule {
  border-collapse: collapse;
  width: 100%;
  min-width: 860px;
}
.schedule th,
.schedule td {
  border: 1px solid rgba(127, 127, 127, 0.25);
  padding: 6px;
  vertical-align: top;
  text-align: left;
}
.schedule th {
  font-weight: 500;
  font-size: 13px;
}
.employee-col {
  width: 180px;
}
.cell {
  height: 56px;
}
.cell.clickable {
  cursor: pointer;
}
.cell.clickable:hover {
  background: rgba(127, 127, 127, 0.08);
}
.today {
  background: rgba(36, 86, 106, 0.07);
}
.weekend {
  color: #b23a3a;
}
.chip {
  color: white;
  border-radius: 4px;
  padding: 2px 6px;
  margin-bottom: 3px;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}
</style>
