<template>
  <q-page padding>
    <div v-if="!h" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" to="/inpatient" />
        <div class="col">
          <div class="text-h5">
            <router-link :to="`/pets/${h.pet}`" class="text-primary" style="text-decoration: none">{{ h.pet_name }}</router-link>
            <q-badge :color="h.status === 'active' ? 'primary' : 'grey-6'" :label="h.status_label" class="q-ml-sm" />
          </div>
          <div class="text-caption text-grey-7">
            {{ h.client_name }} · {{ h.ward_name }}{{ h.place ? `, место ${h.place}` : '' }} · {{ h.doctor_name }} ·
            поступил {{ fmtDate(h.admitted_at) }} · {{ h.status === 'active' ? `${h.days}-е сутки` : `${h.days} сут.` }}
          </div>
        </div>
        <q-btn flat icon="print" label="Лист" @click="printSheet" />
        <q-btn v-if="can('billing.add_invoice')" outline color="primary" icon="receipt_long" label="Счёт" @click="invoice" />
        <q-btn v-if="h.status === 'active' && canEdit" color="positive" unelevated icon="logout" label="Выписать" @click="discharge" />
      </div>
      <div v-if="h.reason" class="q-mb-md"><b>Причина:</b> {{ h.reason }}</div>
      <div v-if="h.outcome" class="q-mb-md"><b>Итог:</b> {{ h.outcome }}</div>

      <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary">
        <q-tab name="sheet" label="Лист назначений" />
        <q-tab name="plans" :label="`Назначения (${plans.filter((p) => p.is_active).length})`" />
        <q-tab name="obs" label="Наблюдение" />
      </q-tabs>
      <q-separator class="q-mb-md" />

      <!-- Лист назначений -->
      <div v-if="tab === 'sheet'">
        <div class="row items-center q-gutter-sm q-mb-sm">
          <q-btn flat round dense icon="chevron_left" @click="shift(-1)" />
          <q-input v-model="day" type="date" dense outlined style="width: 170px" @update:model-value="loadSheet" />
          <q-btn flat round dense icon="chevron_right" @click="shift(1)" />
          <q-btn flat dense no-caps label="Сегодня" @click="day = iso(new Date()); loadSheet()" />
        </div>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="t in sheet" :key="t.id" :class="{ 'row-highlight-negative': t.overdue, 'row-highlight-positive': t.status === 'done' }">
            <q-item-section side class="text-weight-bold" style="width: 64px">{{ time(t.scheduled_at) }}</q-item-section>
            <q-item-section>
              <q-item-label>{{ t.title }} <span class="text-grey-8">{{ t.dose }}</span> <span class="text-caption text-grey-7">· {{ t.route_label }}</span></q-item-label>
              <q-item-label v-if="t.status !== 'planned'" caption>
                {{ t.status === 'done' ? 'выполнено' : 'пропущено' }} {{ t.done_at ? time(t.done_at) : '' }} · {{ t.done_by_name }}{{ t.note ? ` · ${t.note}` : '' }}
              </q-item-label>
              <q-item-label v-else-if="t.overdue" caption class="text-negative">время прошло — не отмечено</q-item-label>
            </q-item-section>
            <q-item-section v-if="canEdit" side>
              <div class="row no-wrap q-gutter-x-xs">
                <template v-if="t.status === 'planned'">
                  <q-btn dense unelevated color="positive" icon="check" @click="mark(t, 'done')"><q-tooltip>Выполнено</q-tooltip></q-btn>
                  <q-btn dense flat color="grey-7" icon="block" @click="skip(t)"><q-tooltip>Пропущено</q-tooltip></q-btn>
                </template>
                <q-btn v-else dense flat icon="undo" @click="mark(t, 'planned')"><q-tooltip>Снять отметку</q-tooltip></q-btn>
              </div>
            </q-item-section>
          </q-item>
          <q-item v-if="!sheet.length"><q-item-section class="text-grey-7">На этот день назначений нет</q-item-section></q-item>
        </q-list>
      </div>

      <!-- Назначения -->
      <div v-if="tab === 'plans'">
        <q-form v-if="h.status === 'active' && canEdit" class="q-gutter-y-sm q-mb-md" @submit="addPlan">
          <div class="row q-col-gutter-sm">
            <!-- Своё название или позиция из прайса (подсказки при вводе) — выбранная из прайса пойдёт в счёт. -->
            <q-input v-model="plan.title" outlined dense class="col-12 col-md-4" label="Препарат или процедура *"
              list="inpatient-catalog" debounce="300" @update:model-value="search"
              :hint="plan.title && itemOf(plan.title) ? 'из прайса — попадёт в счёт' : ''" />
            <datalist id="inpatient-catalog"><option v-for="f in found" :key="f.id" :value="f.name" /></datalist>
            <q-input v-model="plan.dose" outlined dense label="Доза" class="col-6 col-md-2" />
            <q-select v-model="plan.route" :options="ROUTES" emit-value map-options outlined dense label="Способ" class="col-6 col-md-2" />
            <q-select v-model="plan.times" multiple use-chips use-input new-value-mode="add-unique" hide-dropdown-icon outlined dense
              label="Часы (08:00 + Enter)" class="col-12 col-md-4" :options="[]" />
          </div>
          <div class="row q-col-gutter-sm items-center">
            <div class="col-auto q-gutter-x-xs">
              <q-btn v-for="p in PRESETS" :key="p.label" outline dense no-caps size="sm" :label="p.label" @click="plan.times = [...p.times]" />
            </div>
            <q-input v-model="plan.start_date" type="date" stack-label outlined dense label="С даты" class="col-6 col-md-2" />
            <q-input v-model.number="plan.days" type="number" min="1" max="60" outlined dense label="Дней" class="col-6 col-md-1" />
            <q-input v-model="plan.note" outlined dense label="Примечание" class="col-12 col-md" />
          </div>
          <div v-if="error" class="text-negative">{{ error }}</div>
          <div class="q-gutter-x-sm">
            <q-btn type="submit" color="primary" unelevated icon="add" label="Назначить" />
            <q-btn v-if="h.visit" flat no-caps icon="move_down" label="Перенести назначения из медкарты" @click="importVisit" />
          </div>
        </q-form>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="p in plans" :key="p.id" :class="{ 'text-grey-6': !p.is_active }">
            <q-item-section>
              <q-item-label>{{ p.title }} <span>{{ p.dose }}</span> · {{ p.route_label }}</q-item-label>
              <q-item-label caption>{{ p.times.join(', ') }} · с {{ fmtDate(p.start_date) }}, {{ p.days }} дн.{{ p.note ? ` · ${p.note}` : '' }}{{ p.is_active ? '' : ' · отменено' }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="p.is_active && canEdit && h.status === 'active'" side>
              <q-btn flat dense no-caps color="negative" label="Отменить" @click="stopPlan(p)" />
            </q-item-section>
          </q-item>
          <q-item v-if="!plans.length"><q-item-section class="text-grey-7">Назначений нет</q-item-section></q-item>
        </q-list>
      </div>

      <!-- Наблюдение -->
      <div v-if="tab === 'obs'">
        <q-form v-if="h.status === 'active' && canEdit" class="row q-col-gutter-sm items-center q-mb-md" @submit="addObs">
          <q-input v-model="obs.temperature" type="number" step="0.1" outlined dense label="t, °C" class="col-4 col-md-1" />
          <q-input v-model="obs.weight" type="number" step="0.001" outlined dense label="Вес, кг" class="col-4 col-md-1" />
          <q-input v-model="obs.pulse" type="number" outlined dense label="Пульс" class="col-4 col-md-1" />
          <q-input v-model="obs.note" outlined dense label="Состояние, аппетит, стул…" class="col-12 col-md" />
          <div class="col-auto"><q-btn type="submit" color="primary" unelevated icon="add" label="Записать" /></div>
        </q-form>
        <q-markup-table flat bordered dense>
          <thead><tr><th class="text-left">Когда</th><th>t, °C</th><th>Вес</th><th>Пульс</th><th class="text-left">Заметка</th><th class="text-left">Кто</th></tr></thead>
          <tbody>
            <tr v-for="o in observations" :key="o.id">
              <td>{{ fmtDateTime(o.at) }}</td><td class="text-center">{{ o.temperature ?? '' }}</td>
              <td class="text-center">{{ o.weight ? Number(o.weight) : '' }}</td><td class="text-center">{{ o.pulse ?? '' }}</td>
              <td>{{ o.note }}</td><td>{{ o.author_name }}</td>
            </tr>
            <tr v-if="!observations.length"><td colspan="6" class="text-grey-7">Наблюдений нет</td></tr>
          </tbody>
        </q-markup-table>
      </div>
    </template>
  </q-page>
</template>

<script setup>
// Госпитализация: лист назначений по часам с отметками, назначения, наблюдение, счёт, выписка.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const $q = useQuasar()
const canEdit = computed(() => can('inpatient.change_hospitalization'))
const ROUTES = [
  { value: 'oral', label: 'внутрь' }, { value: 'sc', label: 'подкожно' }, { value: 'im', label: 'внутримышечно' },
  { value: 'iv', label: 'внутривенно' }, { value: 'drip', label: 'капельно' }, { value: 'topical', label: 'наружно' },
  { value: 'eyes', label: 'в глаза' }, { value: 'ears', label: 'в уши' }, { value: 'rectal', label: 'ректально' },
  { value: 'procedure', label: 'процедура' }, { value: 'other', label: 'другое' },
]
const PRESETS = [
  { label: '1 раз', times: ['09:00'] }, { label: '2 раза', times: ['08:00', '20:00'] },
  { label: '3 раза', times: ['08:00', '14:00', '20:00'] }, { label: 'каждые 6 ч', times: ['06:00', '12:00', '18:00', '23:00'] },
]
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const time = (v) => new Date(v).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const fmtDate = (v) => new Date(v).toLocaleDateString('ru-RU')
const fmtDateTime = (v) => new Date(v).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const h = ref(null)
const tab = ref('sheet')
const day = ref(iso(new Date()))
const sheet = ref([])
const plans = ref([])
const observations = ref([])
const found = ref([])
const error = ref('')
const emptyPlan = () => ({ item: null, title: '', dose: '', route: 'oral', times: ['08:00', '20:00'], start_date: iso(new Date()), days: 3, note: '' })
const plan = ref(emptyPlan())
const obs = ref({ temperature: '', weight: '', pulse: '', note: '' })
const base = computed(() => `inpatient/hospitalizations/${props.id}`)

const notify = (data, fallback) => $q.notify({ type: 'negative', message: Object.values(fieldErrors(data || {}))[0] || fallback })

async function load() {
  const [main, p, o] = await Promise.all([apiGet(`${base.value}/`), apiGet(`${base.value}/plans/`), apiGet(`${base.value}/observations/`)])
  h.value = main.data
  plans.value = p.data ?? []
  observations.value = o.data ?? []
  loadSheet()
}
async function loadSheet() {
  sheet.value = (await apiGet(`${base.value}/sheet/?date=${day.value}`)).data ?? []
}
function shift(step) {
  const d = new Date(`${day.value}T00:00`)
  d.setDate(d.getDate() + step)
  day.value = iso(d)
  loadSheet()
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

async function search(text) {
  if (!text || text.trim().length < 2) return
  const { ok, data } = await apiGet(`catalog/items/?active=true&page_size=15&search=${encodeURIComponent(text)}`)
  if (ok) found.value = (data.results || []).filter((i) => i.kind !== 'combo').map((i) => ({ id: i.id, name: i.name }))
}
const itemOf = (name) => found.value.find((f) => f.name === name.trim())?.id || null

async function addPlan() {
  error.value = ''
  const { ok, data } = await apiPost(`${base.value}/plans/`, { ...plan.value, item: itemOf(plan.value.title) })
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось назначить')
  plans.value = data
  plan.value = emptyPlan()
  loadSheet()
}
async function stopPlan(p) {
  const { ok, data } = await apiPost(`${base.value}/plans/${p.id}/stop/`)
  if (ok) { plans.value = data; loadSheet() }
}
async function importVisit() {
  const { ok, data } = await apiPost(`${base.value}/import-from-visit/`)
  if (!ok) return notify(data, 'Не удалось перенести')
  $q.notify({ type: 'positive', message: `Перенесено назначений: ${data.imported}. Проверьте часы.` })
  load()
}

async function addObs() {
  const body = Object.fromEntries(Object.entries(obs.value).map(([k, v]) => [k, v === '' ? null : v]))
  const { ok, data } = await apiPost(`${base.value}/observations/`, body)
  if (!ok) return notify(data, 'Не удалось записать')
  observations.value = data
  obs.value = { temperature: '', weight: '', pulse: '', note: '' }
}

function discharge() {
  $q.dialog({ title: 'Выписать?', message: 'Итог лечения (необязательно)', prompt: { model: '', type: 'text' }, cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Выписать', color: 'positive', unelevated: true } }).onOk(async (outcome) => {
    const { ok, data } = await apiPost(`${base.value}/discharge/`, { outcome })
    if (!ok) return notify(data, 'Не удалось выписать')
    h.value = data
    $q.notify({ type: 'positive', message: 'Выписан. Не забудьте выставить счёт за стационар.' })
    load()
  })
}

async function invoice() {
  const { ok, data } = await apiPost(`${base.value}/invoice/`)
  if (!ok) return notify(data, 'Не удалось создать счёт')
  router.push(`/invoices/${data.invoice}`)
}

const printSheet = () => window.open(`/api/${base.value}/print-sheet/?date=${day.value}`, '_blank')

let timer = null
onMounted(() => {
  load()
  timer = setInterval(loadSheet, 60000)
})
onUnmounted(() => clearInterval(timer))
</script>
