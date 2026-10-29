<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none">Календарь</h1>
      <q-space />
      <q-btn flat round icon="chevron_left" @click="shiftDay(-1)" />
      <q-input v-model="day" type="date" dense outlined style="width: 170px" @update:model-value="load" />
      <q-btn flat round icon="chevron_right" @click="shiftDay(1)" />
      <q-btn flat no-caps label="Сегодня" @click="goToday" />
      <q-toggle v-model="showCancelled" label="Отменённые" dense />
    </div>
    <div v-if="hiddenCount" class="text-caption text-grey-7 q-mb-sm">
      Скрыто отменённых и неявок: {{ hiddenCount }} —
      <a href="#" class="text-primary" @click.prevent="showCancelled = true">показать</a>
    </div>

    <div class="calendar-scroll">
      <div class="calendar" :style="{ gridTemplateColumns: `56px repeat(${columns.length}, minmax(160px, 1fr))` }">
        <div class="corner" />
        <div v-for="column in columns" :key="column.id ?? 'none'" class="column-head">
          <q-icon name="circle" :style="{ color: column.color }" size="10px" class="q-mr-xs" />{{ column.name }}
        </div>

        <div class="hours" :style="{ height: `${height}px` }">
          <div v-for="hour in hourMarks" :key="hour" class="hour-label" :style="{ top: `${(hour - startHour) * HOUR}px` }">
            {{ String(hour).padStart(2, '0') }}:00
          </div>
        </div>

        <div v-for="column in columns" :key="`col-${column.id ?? 'none'}`" class="day-column"
          :class="{ clickable: canAdd }" :style="{ height: `${height}px` }" @click="onColumnClick(column, $event)">
          <div v-for="hour in hourMarks" :key="hour" class="hour-line" :style="{ top: `${(hour - startHour) * HOUR}px` }" />
          <div v-for="(interval, i) in column.intervals.filter((x) => x.is_working)" :key="`w${i}`" class="working"
            :style="block(interval)" />
          <div v-if="nowTop !== null" class="now-line" :style="{ top: `${nowTop}px` }" />
          <div v-for="item in appointmentsOf(column)" :key="item.id" class="appointment"
            :class="[item.status, { overdue: item.is_overdue }]"
            :style="{ ...block(item), borderLeftColor: item.purpose_color || '#24566a' }" @click.stop="openView(item)">
            <div class="text-weight-medium ellipsis">{{ timeOf(item.start) }} {{ item.client_name }}</div>
            <div class="ellipsis text-caption">{{ [item.pet_name, item.purpose_name].filter(Boolean).join(' · ') }}</div>
            <q-badge v-if="item.status !== 'planned'" :color="STATUS[item.status].color" :label="item.status_label"
              class="status-badge" />
          </div>
        </div>
      </div>
    </div>

    <AppointmentDialog v-model="editorOpen" :appointment="editing" :preset="preset" :doctors="doctorOptions" @saved="load" />
    <AppointmentView v-model="viewOpen" :appointment="viewing" @changed="load" @edit="editAppointment" />
  </q-page>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import AppointmentDialog from './AppointmentDialog.vue'
import AppointmentView from './AppointmentView.vue'
import { isoDate, STATUS, timeOf } from './appointments'

const HOUR = 64 // высота часа на экране, px
const canAdd = can('scheduling.add_appointment')
const day = ref(isoDate(new Date()))
const data = ref({ doctors: [], appointments: [] })
const showCancelled = ref(false)
const now = ref(new Date())

async function load() {
  data.value = (await apiGet(`scheduling/calendar/?date=${day.value}`)).data ?? { doctors: [], appointments: [] }
}
function shiftDay(step) {
  const d = new Date(`${day.value}T00:00`)
  d.setDate(d.getDate() + step)
  day.value = isoDate(d)
  load()
}
function goToday() {
  day.value = isoDate(new Date())
  load()
}

const dayStart = computed(() => new Date(`${day.value}T00:00`))
const minutesFromDayStart = (iso) => (new Date(iso) - dayStart.value) / 60000

// Часы на экране: по графику врачей и записям, но не меньше 8:00–21:00.
const startHour = computed(() => {
  const starts = [...data.value.doctors.flatMap((d) => d.intervals), ...data.value.appointments].map((x) => minutesFromDayStart(x.start) / 60)
  return Math.max(0, Math.min(8, ...starts.map(Math.floor)))
})
const endHour = computed(() => {
  const ends = [...data.value.doctors.flatMap((d) => d.intervals), ...data.value.appointments].map((x) => minutesFromDayStart(x.end) / 60)
  return Math.min(24, Math.max(21, ...ends.map(Math.ceil)))
})
const height = computed(() => (endHour.value - startHour.value) * HOUR)
const hourMarks = computed(() => Array.from({ length: endHour.value - startHour.value }, (_, i) => startHour.value + i))

function block(item) {
  const top = Math.max(0, (minutesFromDayStart(item.start) / 60 - startHour.value) * HOUR)
  const bottom = Math.min(height.value, (minutesFromDayStart(item.end) / 60 - startHour.value) * HOUR)
  return { top: `${top}px`, height: `${Math.max(22, bottom - top)}px` }
}

const nowTop = computed(() => {
  if (day.value !== isoDate(now.value)) return null
  const top = ((now.value - dayStart.value) / 3600000 - startHour.value) * HOUR
  return top >= 0 && top <= height.value ? top : null
})

const columns = computed(() => [
  ...data.value.doctors.map((d) => ({ ...d })),
  { id: null, name: 'Любой врач', color: '#8a8a8a', intervals: [] },
])
const doctorOptions = computed(() => data.value.doctors.map((d) => ({ id: d.id, name: d.name })))
const visible = (item) => showCancelled.value || !['cancelled', 'no_show'].includes(item.status)
const appointmentsOf = (column) => data.value.appointments.filter((a) => (a.doctor ?? null) === column.id && visible(a))
const hiddenCount = computed(() => data.value.appointments.filter((a) => !visible(a)).length)

// --- запись кликом по свободному месту ---
const editorOpen = ref(false)
const editing = ref(null)
const preset = ref({})
function onColumnClick(column, event) {
  if (!canAdd) return
  const rect = event.currentTarget.getBoundingClientRect()
  const minutes = Math.floor(((event.clientY - rect.top) / HOUR) * 60 / 15) * 15 + startHour.value * 60
  const start = new Date(dayStart.value.getTime() + minutes * 60000)
  editing.value = null
  preset.value = { start, doctor: column.id }
  editorOpen.value = true
}

const viewOpen = ref(false)
const viewing = ref(null)
function openView(item) {
  viewing.value = item
  viewOpen.value = true
}
function editAppointment(item) {
  viewOpen.value = false
  editing.value = item
  preset.value = {}
  editorOpen.value = true
}

let timer = null
onMounted(() => {
  load()
  timer = setInterval(() => (now.value = new Date()), 60000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.calendar-scroll {
  overflow-x: auto;
}
.calendar {
  display: grid;
  min-width: 560px;
}
.column-head,
.corner {
  position: sticky;
  top: 0;
  z-index: 3;
  background: white;
  padding: 6px;
  font-weight: 500;
  border-bottom: 1px solid rgba(127, 127, 127, 0.3);
}
body.body--dark .column-head,
body.body--dark .corner {
  background: #121212;
}
.hours {
  position: relative;
}
.hour-label {
  position: absolute;
  right: 6px;
  font-size: 11px;
  color: #888;
  transform: translateY(-6px);
}
.day-column {
  position: relative;
  border-left: 1px solid rgba(127, 127, 127, 0.25);
}
.day-column.clickable {
  cursor: copy;
}
.hour-line {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px solid rgba(127, 127, 127, 0.15);
}
.working {
  position: absolute;
  left: 0;
  right: 0;
  background: rgba(60, 122, 78, 0.08);
}
.now-line {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 2px solid #b23a3a;
  z-index: 2;
}
.appointment {
  position: absolute;
  left: 3px;
  right: 3px;
  z-index: 1;
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 4px;
  border-left: 4px solid;
  background: #e8eff2;
  color: #1d2326;
  font-size: 12px;
  line-height: 1.3;
  cursor: pointer;
}
.appointment.waiting {
  background: #fdf1d8;
}
.appointment.in_progress {
  background: #dcebf5;
}
.appointment.completed {
  background: #e3efe6;
}
.appointment.cancelled,
.appointment.no_show {
  opacity: 0.55;
  text-decoration: line-through;
}
.appointment.overdue {
  outline: 2px solid #b23a3a;
}
.status-badge {
  position: absolute;
  right: 3px;
  top: 3px;
}
</style>
