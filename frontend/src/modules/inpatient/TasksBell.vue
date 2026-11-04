<template>
  <q-btn flat round icon="notifications" :color="overdue ? 'red-3' : undefined">
    <q-badge v-if="tasks.length" floating :color="overdue ? 'negative' : 'warning'" :label="tasks.length" />
    <q-tooltip>Стационар: пора выполнить назначения</q-tooltip>
    <q-menu anchor="bottom right" self="top right" style="min-width: 360px; max-width: 95vw" @show="load">
      <q-list dense>
        <q-item-label header class="row items-center">
          <span class="col">Стационар — пора выполнить</span>
          <q-toggle v-if="canSeeAll" v-model="everyone" dense size="sm" label="все пациенты" @update:model-value="saveMode" />
        </q-item-label>
        <q-item v-for="t in tasks" :key="t.id" clickable @click="$router.push(`/inpatient/${t.hospitalization}`)">
          <q-item-section side class="text-weight-bold" :class="t.overdue ? 'text-negative' : ''" style="min-width: 52px">
            {{ time(t.scheduled_at) }}
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ t.pet_name }} · {{ t.title }} <span class="text-grey-7">{{ t.dose }}</span></q-item-label>
            <q-item-label caption>{{ t.ward }}{{ t.place ? `, место ${t.place}` : '' }} · {{ t.route_label }}{{ t.overdue ? ' · просрочено' : '' }}</q-item-label>
          </q-item-section>
          <q-item-section v-if="canMark" side>
            <q-btn dense unelevated color="positive" icon="check" @click.stop="done(t)"><q-tooltip>Выполнено</q-tooltip></q-btn>
          </q-item-section>
        </q-item>
        <q-item v-if="!tasks.length"><q-item-section class="text-grey-7">Сейчас выполнять нечего</q-item-section></q-item>
        <q-separator />
        <q-item v-if="permission === 'default'" clickable @click="enableNotifications">
          <q-item-section avatar><q-icon name="notifications_active" /></q-item-section>
          <q-item-section>Включить уведомления на этом компьютере</q-item-section>
        </q-item>
        <q-item v-else-if="permission === 'denied'">
          <q-item-section class="text-caption text-grey-7">Уведомления запрещены в настройках браузера — их можно разрешить для этого сайта</q-item-section>
        </q-item>
        <q-item v-else-if="permission === 'granted'">
          <q-item-section class="text-caption text-grey-7">Уведомления включены: о каждом назначении придёт сообщение, когда наступит его время</q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup>
// Напоминания персоналу стационара: назначения моих пациентов (ответственный или лечащий врач),
// просроченные и на ближайшие 30 минут. Проверка раз в минуту; при наступлении времени —
// уведомление браузера (если разрешено). Работает, пока открыта любая страница системы.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiGet, apiPost } from '@/api'
import { can } from '@/session'

const tasks = ref([])
const canSeeAll = can('inpatient.change_hospitalization')
const canMark = can('inpatient.change_hospitalization')
const everyone = ref(canSeeAll && localStorage.getItem('inpatient.bell.all') === '1')
const permission = ref(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission)
const overdue = computed(() => tasks.value.some((t) => t.overdue))
const notified = new Set()
let timer = null
const time = (v) => new Date(v).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

async function load() {
  const { ok, data } = await apiGet(`inpatient/hospitalizations/my-tasks/${everyone.value ? '?all=1' : ''}`)
  if (!ok) return
  tasks.value = data
  notify()
}

// Уведомление — один раз на назначение, когда наступило его время.
function notify() {
  if (permission.value !== 'granted') return
  for (const t of tasks.value) {
    if (notified.has(t.id) || new Date(t.scheduled_at) > new Date()) continue
    notified.add(t.id)
    const n = new Notification(`Стационар: ${t.pet_name}`, {
      body: `${time(t.scheduled_at)} — ${t.title} ${t.dose} (${t.route_label}), ${t.ward}`, tag: `task-${t.id}`,
    })
    n.onclick = () => { window.focus(); window.location.assign(`/inpatient/${t.hospitalization}`) }
  }
}

async function enableNotifications() {
  permission.value = await Notification.requestPermission()
  notify()
}

async function done(task) {
  const { ok } = await apiPost(`inpatient/hospitalizations/${task.hospitalization}/tasks/${task.id}/mark/`, { status: 'done' })
  if (ok) load()
}

function saveMode(value) {
  localStorage.setItem('inpatient.bell.all', value ? '1' : '0')
  load()
}

onMounted(() => {
  load()
  timer = setInterval(load, 60000)
})
onUnmounted(() => clearInterval(timer))
</script>
