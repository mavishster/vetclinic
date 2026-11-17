<template>
  <q-page class="cage q-pa-sm">
    <div v-if="denied" class="text-center q-pa-xl">
      <q-icon name="lock" size="48px" color="grey-6" />
      <div class="text-h6 q-mt-sm">Нет доступа</div>
      <div class="text-grey-7">Доступ к стационару выдаёт тот, кто настраивает роли.</div>
    </div>
    <div v-else-if="!h" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <q-card flat bordered class="q-mb-sm">
        <q-card-section class="q-pb-sm">
          <div class="row items-center no-wrap">
            <div class="col text-h5 text-weight-bold">{{ h.pet_name }}</div>
            <q-badge :color="active ? 'primary' : 'grey-6'" :label="h.status_label" />
          </div>
          <div class="text-body2 text-grey-8">{{ [h.cage?.species_breed, h.cage?.age, h.cage?.weight].filter(Boolean).join(' · ') }}</div>
          <div v-if="h.cage?.diagnosis" class="q-mt-xs"><b>Диагноз:</b> {{ h.cage.diagnosis }}</div>
          <div class="text-caption text-grey-7 q-mt-xs">
            {{ h.ward_name }}{{ h.place ? `, место ${h.place}` : '' }} · {{ active ? `${h.days}-е сутки` : `${h.days} сут.` }} · врач {{ h.doctor_name }}
          </div>
          <div v-if="h.staff_names?.length" class="text-caption text-grey-7">Ответственные: {{ h.staff_names.join(', ') }}</div>
        </q-card-section>
        <q-banner v-if="!active" class="bg-grey-3">
          <b>Выписан {{ h.discharged_at ? fmtDate(h.discharged_at) : '' }}.</b>
          <span v-if="h.outcome"> Итог: {{ h.outcome }}</span>
        </q-banner>
      </q-card>

      <q-tabs v-model="tab" dense no-caps active-color="primary" indicator-color="primary" class="q-mb-sm">
        <q-tab name="today" label="Сегодня" />
        <q-tab name="obs" label="Наблюдение" />
        <q-tab name="info" label="Инфо" />
      </q-tabs>

      <!-- Сегодня: крупные кнопки отметки -->
      <div v-if="tab === 'today'">
        <div v-for="t in sheet" :key="t.id" class="task q-pa-sm q-mb-sm rounded-borders"
          :class="{ overdue: t.overdue, done: t.status === 'done', skipped: t.status === 'skipped' }">
          <div class="row items-center no-wrap">
            <div class="col">
              <div class="text-weight-bold">{{ windowText(t) }}</div>
              <div class="text-subtitle1">{{ t.title }} <span class="text-grey-8">{{ t.dose }}</span></div>
              <div class="text-caption text-grey-7">{{ t.route_label }}</div>
              <div v-if="t.status !== 'planned'" class="text-caption">
                {{ t.status === 'done' ? 'выполнено' : 'пропущено' }} {{ t.done_at ? time(t.done_at) : '' }} · {{ t.done_by_name }}{{ t.note ? ` · ${t.note}` : '' }}
              </div>
              <div v-else-if="t.overdue" class="text-caption text-negative">срок{{ t.due_until ? ` до ${time(t.due_until)}` : '' }} прошёл — не отмечено</div>
            </div>
            <div v-if="canEdit" class="column q-gutter-y-xs" style="min-width: 108px">
              <template v-if="t.status === 'planned'">
                <q-btn unelevated color="positive" icon="check" label="Выполнено" no-caps size="md" @click="mark(t, 'done')" />
                <q-btn flat color="grey-8" label="Пропустить" no-caps size="sm" @click="skip(t)" />
              </template>
              <q-btn v-else flat icon="undo" label="Снять" no-caps size="sm" @click="mark(t, 'planned')" />
            </div>
          </div>
        </div>
        <div v-if="!sheet.length" class="text-grey-7 text-center q-pa-md">На сегодня назначений нет</div>
      </div>

      <!-- Наблюдение -->
      <div v-if="tab === 'obs'">
        <q-form v-if="active && canEdit" class="q-gutter-y-sm q-mb-md" @submit="addObs">
          <div class="row q-col-gutter-sm">
            <q-input v-model="obs.temperature" type="number" step="0.1" inputmode="decimal" outlined dense label="t, °C" class="col-4" />
            <q-input v-model="obs.weight" type="number" step="0.001" inputmode="decimal" outlined dense label="Вес, кг" class="col-4" />
            <q-input v-model="obs.pulse" type="number" inputmode="numeric" outlined dense label="Пульс" class="col-4" />
          </div>
          <q-input v-model="obs.note" outlined dense label="Состояние, аппетит, стул…" />
          <q-btn type="submit" color="primary" unelevated no-caps icon="add" label="Записать" class="full-width" />
        </q-form>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="o in observations" :key="o.id">
            <q-item-section>
              <q-item-label>{{ [o.temperature != null ? `${o.temperature} °C` : '', o.weight ? `${Number(o.weight)} кг` : '', o.pulse != null ? `пульс ${o.pulse}` : ''].filter(Boolean).join(' · ') }}</q-item-label>
              <q-item-label v-if="o.note">{{ o.note }}</q-item-label>
              <q-item-label caption>{{ fmtDateTime(o.at) }} · {{ o.author_name }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-if="!observations.length"><q-item-section class="text-grey-7">Наблюдений нет</q-item-section></q-item>
        </q-list>
      </div>

      <!-- Инфо -->
      <div v-if="tab === 'info'" class="q-gutter-y-sm">
        <div v-if="h.reason"><b>Причина:</b> {{ h.reason }}</div>
        <div><b>Поступил:</b> {{ fmtDate(h.admitted_at) }}</div>
        <div v-if="h.cage?.owner_phone"><b>Владелец:</b> {{ h.client_name }}, <a :href="`tel:${h.cage.owner_phone}`">{{ h.cage.owner_phone }}</a></div>
        <div class="text-subtitle2 q-mt-md">Назначения</div>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="p in plans" :key="p.id" :class="{ 'text-grey-6': !p.is_active }">
            <q-item-section>
              <q-item-label>{{ p.title }} {{ p.dose }} · {{ p.route_label }}</q-item-label>
              <q-item-label caption>{{ p.times.join(', ') }} · с {{ fmtDate(p.start_date) }}, {{ p.days }} дн.{{ p.is_active ? '' : ' · отменено' }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-if="!plans.length"><q-item-section class="text-grey-7">Назначений нет</q-item-section></q-item>
        </q-list>
        <q-btn flat no-caps color="primary" icon="open_in_full" label="Полная страница пациента" :to="{ query: { full: 1 } }" />
      </div>
    </template>
  </q-page>
</template>

<script setup>
// Экран «у клетки»: открывается по QR на телефоне. Шапка пациента, лист назначений на сегодня
// с крупными кнопками, быстрое наблюдение. Права — по ролям; без права данные не приходят.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({ id: { type: String, required: true } })
const $q = useQuasar()
const h = ref(null)
const denied = ref(false)
const tab = ref('today')
const sheet = ref([])
const plans = ref([])
const observations = ref([])
const obs = ref({ temperature: '', weight: '', pulse: '', note: '' })
const base = computed(() => `inpatient/hospitalizations/${props.id}`)
const active = computed(() => h.value?.status === 'active')
const canEdit = computed(() => can('inpatient.change_hospitalization') && active.value)

const time = (v) => new Date(v).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const windowText = (t) => (t.due_until ? `${time(t.scheduled_at)}–${time(t.due_until)}` : time(t.scheduled_at))
const fmtDate = (v) => new Date(v).toLocaleDateString('ru-RU')
const fmtDateTime = (v) => new Date(v).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const notify = (data, fallback) => $q.notify({ type: 'negative', message: Object.values(fieldErrors(data || {}))[0] || fallback })

async function load() {
  const main = await apiGet(`${base.value}/`)
  if (!main.ok) {
    denied.value = main.status === 403 || main.status === 404
    return
  }
  h.value = main.data
  const [p, o] = await Promise.all([apiGet(`${base.value}/plans/`), apiGet(`${base.value}/observations/`)])
  plans.value = p.data ?? []
  observations.value = o.data ?? []
  await loadSheet()
}
async function loadSheet() {
  const { ok, data } = await apiGet(`${base.value}/sheet/?date=${today()}`)
  if (ok) sheet.value = data
}

async function mark(task, status, note = '') {
  const { ok, data } = await apiPost(`${base.value}/tasks/${task.id}/mark/`, { status, note })
  if (!ok) return notify(data, 'Не удалось отметить')
  Object.assign(task, data)
}
function skip(task) {
  $q.dialog({ title: 'Пропущено', message: 'Почему?', prompt: { model: '', type: 'text' }, cancel: { label: 'Назад', flat: true },
    ok: { label: 'Отметить', color: 'primary', unelevated: true } }).onOk((note) => mark(task, 'skipped', note))
}
async function addObs() {
  const body = Object.fromEntries(Object.entries(obs.value).map(([k, v]) => [k, v === '' ? null : v]))
  const { ok, data } = await apiPost(`${base.value}/observations/`, body)
  if (!ok) return notify(data, 'Не удалось записать')
  observations.value = data
  obs.value = { temperature: '', weight: '', pulse: '', note: '' }
}

let timer = null
onMounted(() => {
  load()
  timer = setInterval(loadSheet, 60000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.task { border: 1px solid rgba(128, 128, 128, 0.35); }
.task.overdue { background: rgba(244, 67, 54, 0.12); border-color: #e53935; }
.task.done { background: rgba(76, 175, 80, 0.14); }
.task.skipped { opacity: 0.7; }
</style>
