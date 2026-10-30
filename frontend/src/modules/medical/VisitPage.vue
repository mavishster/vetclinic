<template>
  <q-page padding>
    <div v-if="!visit" class="flex flex-center q-pa-xl">
      <q-spinner v-if="loading" size="40px" color="primary" />
      <div v-else class="text-grey-7">Запись не найдена.</div>
    </div>

    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" @click="$router.back()" />
        <div>
          <div class="text-h5">
            <router-link :to="`/pets/${visit.pet}`" class="text-primary" style="text-decoration: none">{{ visit.pet_name }}</router-link>
          </div>
          <div class="text-caption text-grey-7">
            владелец: <router-link :to="`/clients/${visit.client}`" class="text-grey-8">{{ visit.client_name }}</router-link>
          </div>
        </div>
        <q-space />
        <div class="text-caption text-grey-7">
          <q-icon :name="saveState === 'error' ? 'error' : saveState === 'saving' ? 'sync' : 'cloud_done'"
            :color="saveState === 'error' ? 'negative' : 'grey-6'" /> {{ saveText }}
        </div>
        <q-btn outline color="primary" icon="print" label="Печать" @click="print" />
        <q-btn v-if="can('medical.delete_visit')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
        <q-btn v-if="visit.appointment_status === 'in_progress' && canEdit" color="positive" unelevated icon="task_alt"
          label="Завершить приём" @click="complete" />
      </div>

      <div class="row q-col-gutter-md">
        <div class="col-12 col-md-3 q-gutter-y-sm">
          <q-input v-model="dateText" type="datetime-local" label="Дата и время" stack-label outlined dense :readonly="!canEdit" />
          <div class="row q-col-gutter-sm">
            <q-input v-model="form.weight" type="number" step="0.001" min="0" label="Вес, кг" outlined dense class="col-6" :readonly="!canEdit" />
            <q-input v-model="form.temperature" type="number" step="0.1" label="t, °C" outlined dense class="col-6" :readonly="!canEdit" />
          </div>
          <q-select v-model="form.purpose" :options="purposes" option-value="id" option-label="name" emit-value map-options
            outlined dense label="Цель обращения" :readonly="!canEdit" />
          <q-select v-model="form.result" :options="results" option-value="id" option-label="name" emit-value map-options
            outlined dense clearable label="Результат посещения" :readonly="!canEdit" />
          <div class="text-subtitle2 q-pt-sm">Диагнозы</div>
          <div v-for="(d, i) in form.diagnoses" :key="i" class="row items-center no-wrap q-gutter-x-xs">
            <q-select v-model="d.diagnosis" :options="diagnosisOptions" option-value="id" option-label="name" emit-value
              map-options use-input input-debounce="0" outlined dense class="col" :readonly="!canEdit" @filter="filterDiagnoses" />
            <q-btn flat dense round size="sm" :icon="d.kind === 'final' ? 'verified' : 'help_outline'"
              :color="d.kind === 'final' ? 'positive' : 'grey-7'" :disable="!canEdit"
              @click="d.kind = d.kind === 'final' ? 'preliminary' : 'final'">
              <q-tooltip>{{ d.kind === 'final' ? 'Окончательный' : 'Предварительный' }} — нажмите, чтобы сменить</q-tooltip>
            </q-btn>
            <q-btn v-if="canEdit" flat dense round size="sm" icon="close" color="grey-7" @click="form.diagnoses.splice(i, 1)" />
          </div>
          <q-btn v-if="canEdit" flat dense no-caps color="primary" icon="add" label="Диагноз"
            @click="form.diagnoses.push({ diagnosis: null, kind: 'preliminary' })" />
          <q-input v-model="form.next_visit_date" type="date" label="Повторный приём" stack-label outlined dense clearable :readonly="!canEdit" />
          <q-select v-model="form.doctor" :options="doctors" option-value="id" option-label="name" emit-value map-options
            outlined dense label="Врач" :readonly="!canEdit" />
        </div>

        <div class="col-12 col-md-6">
          <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary">
            <q-tab name="treatment" label="Описание лечения" />
            <q-tab name="recommendations" label="Рекомендации и назначения" />
            <q-tab name="prevention" :label="`Профилактика${visit.preventions.length ? ` (${visit.preventions.length})` : ''}`" />
            <q-tab name="history" label="История" />
            <q-tab name="files" label="Файлы" />
          </q-tabs>
          <q-separator />
          <q-banner v-if="canEdit && visit.prevention_suggestions.length" dense class="bg-blue-1 text-dark q-mt-sm" rounded>
            <template #avatar><q-icon name="health_and_safety" color="primary" /></template>
            В записи отмечено то, что стоит внести в профилактику:
            <q-btn v-for="s in visit.prevention_suggestions" :key="s.type + s.item" flat dense no-caps color="primary"
              :label="`${s.type_name}: ${s.item_name}`" @click="suggest(s)" />
          </q-banner>
          <q-tab-panels v-model="tab" keep-alive animated class="bg-transparent">
            <q-tab-panel name="treatment" class="q-px-none">
              <RichEditor v-model="form.treatment_html" placeholder="Жалобы, анамнез, осмотр, что сделано на приёме…" />
            </q-tab-panel>
            <q-tab-panel name="recommendations" class="q-px-none">
              <RichEditor v-model="form.recommendations_html" placeholder="Рекомендации владельцу, назначения, питание…" />
            </q-tab-panel>
            <q-tab-panel name="prevention" class="q-px-none">
              <PreventionPanel :visit="visit" :can-edit="canEdit" :prefill="prefill" @changed="(v) => (visit = v)" />
            </q-tab-panel>
            <q-tab-panel name="history" class="q-px-none">
              <q-list separator bordered class="rounded-borders">
                <q-item v-for="h in history" :key="h.id" clickable :to="`/visits/${h.id}`" :active="h.id === visit.id">
                  <q-item-section>
                    <q-item-label>{{ new Date(h.date).toLocaleDateString('ru-RU') }} · {{ h.purpose_name }}</q-item-label>
                    <q-item-label caption>{{ h.diagnoses.map((d) => d.name).join(', ') || 'без диагноза' }} · {{ h.doctor_name }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-tab-panel>
            <q-tab-panel name="files" class="q-px-none">
              <AttachmentsBlock owner-type="medical.visit" :owner-id="visit.id" title="Файлы приёма" />
            </q-tab-panel>
          </q-tab-panels>
        </div>

        <div class="col-12 col-md-3">
          <q-card flat bordered>
            <q-card-section class="text-subtitle2">Позиции для счёта</q-card-section>
            <q-list dense>
              <q-item v-for="(item, i) in visit.items" :key="i">
                <q-item-section>
                  <q-item-label>{{ item.name }}</q-item-label>
                  <q-item-label caption>{{ item.unit }} × {{ Number(item.quantity) }} · {{ item.section === 'treatment' ? 'лечение' : 'рекомендации' }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="!visit.items.length">
                <q-item-section class="text-grey-7 text-caption">Отмеченные через «@» позиции появятся здесь после сохранения.</q-item-section>
              </q-item>
            </q-list>
          </q-card>
          <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
        </div>
      </div>
    </template>
  </q-page>
</template>

<script setup>
// Запись медкарты. Изменения сохраняются сами через пару секунд после ввода —
// ничего не потеряется, даже если врача отвлекли посреди записи.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import AttachmentsBlock from '@/components/AttachmentsBlock.vue'
import RichEditor from './RichEditor.vue'
import PreventionPanel from './PreventionPanel.vue'

const props = defineProps({ id: { type: String, required: true } })
const $q = useQuasar()
const router = useRouter()
const canEdit = can('medical.change_visit')
const visit = ref(null)
const form = ref({})
const loading = ref(true)
const tab = ref('treatment')
const purposes = ref([])
const results = ref([])
const diagnoses = ref([])
const doctors = ref([])
const diagnosisOptions = ref([])
const history = ref([])
const prefill = ref(null)

// Подсказка из отмеченных позиций: открыть «Профилактику» с заполненной формой.
function suggest(suggestion) {
  prefill.value = { ...suggestion }
  tab.value = 'prevention'
}
const error = ref('')
const saveState = ref('saved') // saved | dirty | saving | error
const savedAt = ref(null)

const FIELDS = ['date', 'doctor', 'weight', 'temperature', 'purpose', 'result', 'treatment_html', 'recommendations_html', 'next_visit_date']
const pad = (n) => String(n).padStart(2, '0')
const toLocalInput = (iso) => {
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const dateText = computed({
  get: () => (form.value.date ? toLocalInput(form.value.date) : ''),
  set: (value) => (form.value.date = new Date(value).toISOString()),
})
const saveText = computed(() => ({
  saved: savedAt.value ? `Сохранено в ${savedAt.value}` : 'Сохранено',
  dirty: 'Есть изменения…', saving: 'Сохраняю…', error: 'Не сохранено',
})[saveState.value])

function fillForm(data) {
  form.value = Object.fromEntries(FIELDS.map((f) => [f, data[f]]))
  form.value.diagnoses = data.diagnoses.map((d) => ({ diagnosis: d.diagnosis, kind: d.kind }))
}

async function load() {
  loading.value = true
  const { ok, data } = await apiGet(`medical/visits/${props.id}/`)
  visit.value = ok ? data : null
  if (ok) {
    fillForm(data)
    history.value = (await apiGet(`medical/visits/?pet=${data.pet}&page_size=100`)).data?.results ?? []
  }
  loading.value = false
  saveState.value = 'saved'
}

let timer = null
let skipNext = true
watch(form, () => {
  if (skipNext) return (skipNext = false)
  if (!canEdit) return
  saveState.value = 'dirty'
  clearTimeout(timer)
  timer = setTimeout(save, 2500)
}, { deep: true })

const clean = (v) => (v === '' || v === undefined ? null : v)
async function save() {
  clearTimeout(timer)
  if (saveState.value !== 'dirty') return
  saveState.value = 'saving'
  const body = {
    ...form.value, weight: clean(form.value.weight), temperature: clean(form.value.temperature),
    next_visit_date: clean(form.value.next_visit_date),
    diagnoses: form.value.diagnoses.filter((d) => d.diagnosis),
  }
  const { ok, data } = await apiPatch(`medical/visits/${props.id}/`, body)
  if (!ok) {
    saveState.value = 'error'
    error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить'
    return
  }
  error.value = ''
  visit.value = data
  saveState.value = 'saved'
  savedAt.value = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const filterDiagnoses = (text, update) =>
  update(() => (diagnosisOptions.value = diagnoses.value.filter((d) => d.name.toLowerCase().includes(text.toLowerCase()))))

async function complete() {
  await save()
  const { ok, data } = await apiPost(`medical/visits/${props.id}/complete/`)
  if (ok) {
    visit.value = data
    $q.notify({ type: 'positive', message: 'Приём завершён' })
  }
}

function remove() {
  $q.dialog({
    title: 'Удалить запись медкарты?',
    message: 'Запись и процедуры профилактики этого приёма исчезнут из медкарты и отчётов. Отметки в карточке питомца (стерилизация, чип) и вес останутся — при необходимости исправьте их в карточке.',
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
    persistent: true,
  }).onOk(async () => {
    clearTimeout(timer)
    saveState.value = 'saved' // несохранённое удаляемой записи сохранять не нужно
    const pet = visit.value.pet
    const { ok } = await apiDelete(`medical/visits/${props.id}/`)
    if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось удалить запись' })
    $q.notify({ type: 'positive', message: 'Запись медкарты удалена' })
    router.push(`/pets/${pet}`)
  })
}

async function print() {
  await save()
  window.open(`/api/medical/visits/${props.id}/print/`, '_blank')
}

watch(() => props.id, () => {
  skipNext = true
  load()
})
onMounted(async () => {
  const [p, r, d, doc] = await Promise.all([
    apiGet('scheduling/purposes/?active=true'), apiGet('medical/results/?active=true'), apiGet('medical/diagnoses/?active=true'),
    apiGet('medical/visits/doctors/'),
  ])
  doctors.value = doc.data ?? []
  purposes.value = p.data ?? []
  results.value = r.data ?? []
  diagnoses.value = diagnosisOptions.value = d.data ?? []
  await load()
})
onBeforeUnmount(save) // уходя со страницы — сохраняем несохранённое
</script>
