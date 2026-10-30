<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.sm" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 920px; max-width: 96vw">
      <q-form @submit="save">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ form.id ? 'Изменить клиента' : 'Новый клиент' }}</div>
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="duplicates.length" class="q-pt-none">
          <q-banner rounded class="bg-amber-1 text-dark">
            <template #avatar><q-icon name="warning" color="warning" /></template>
            <div class="text-weight-medium q-mb-xs">Возможно, клиент уже есть в базе:</div>
            <div v-for="dup in duplicates" :key="dup.id" class="row items-center q-gutter-x-sm q-py-xs">
              <span class="text-weight-medium">{{ dup.full_name }}</span>
              <span class="text-grey-8">{{ [dup.phones.join(', '), dup.city].filter(Boolean).join(' · ') }}</span>
              <q-badge v-for="reason in dup.reasons" :key="reason" outline color="primary"
                :label="reason === 'phone' ? 'совпал телефон' : 'похожее ФИО'" />
              <q-badge v-if="dup.status !== 'active'" :color="STATUS[dup.status].color" :label="STATUS[dup.status].label" />
              <q-btn flat dense no-caps color="primary" label="Открыть" @click="openDuplicate(dup.id)" />
            </div>
          </q-banner>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6 q-gutter-y-sm">
              <div class="text-subtitle2 text-grey-8">Клиент</div>
              <q-input v-model="form.last_name" label="Фамилия *" outlined dense autofocus
                :error="!!errors.last_name" :error-message="errors.last_name" />
              <div class="row q-col-gutter-sm">
                <q-input v-model="form.first_name" label="Имя" outlined dense class="col-6" />
                <q-input v-model="form.middle_name" label="Отчество" outlined dense class="col-6" />
              </div>

              <div class="text-subtitle2 text-grey-8 q-pt-sm">Телефоны</div>
              <div v-for="(phone, index) in form.phones" :key="index" class="row q-col-gutter-xs items-center">
                <q-input v-model="phone.number" outlined dense placeholder="+7 900 000-00-00" class="col" inputmode="tel" />
                <q-select v-model="phone.kind" :options="PHONE_KINDS" emit-value map-options outlined dense class="col-4" />
                <div class="col-auto">
                  <q-btn flat round dense :icon="phone.is_primary ? 'star' : 'star_outline'"
                    :color="phone.is_primary ? 'accent' : 'grey-6'" @click="makePrimary(index)">
                    <q-tooltip>Основной телефон</q-tooltip>
                  </q-btn>
                  <q-btn flat round dense icon="close" color="grey-7" @click="form.phones.splice(index, 1)" />
                </div>
              </div>
              <q-btn flat dense no-caps color="primary" icon="add" label="Добавить телефон"
                @click="form.phones.push({ number: '', kind: 'mobile', is_primary: !form.phones.length })" />

              <div class="text-subtitle2 text-grey-8 q-pt-sm">Адрес</div>
              <div class="row q-col-gutter-sm">
                <q-select v-model="form.city" :options="cities" option-value="id" option-label="name" emit-value
                  map-options outlined dense clearable use-input input-debounce="0" new-value-mode="add-unique"
                  label="Город" class="col-12 col-sm-6" @filter="filterCities" @new-value="addCity"
                  @update:model-value="form.street = null" />
                <q-select v-model="form.street" :options="streets" option-value="id" option-label="name"
                  emit-value map-options outlined dense clearable use-input input-debounce="0"
                  new-value-mode="add-unique" :disable="!form.city" label="Улица" class="col-12 col-sm-6"
                  @filter="filterStreets" @new-value="addStreet" />
                <q-input v-model="form.house" label="Дом, квартира" outlined dense class="col-8" />
                <q-input v-model="form.zip_code" label="Индекс" outlined dense class="col-4" />
              </div>
              <q-input v-model="form.email" label="Email" type="email" outlined dense
                :error="!!errors.email" :error-message="errors.email" />
            </div>

            <div class="col-12 col-md-6 q-gutter-y-sm">
              <div class="text-subtitle2 text-grey-8">Прочее</div>
              <div class="row q-col-gutter-sm">
                <q-input v-model="form.discount_percent" label="Скидка, %" type="number" min="0" max="100" step="0.5"
                  outlined dense class="col-4" :error="!!errors.discount_percent" :error-message="errors.discount_percent" />
                <q-input v-model="form.journal_number" label="№ по журналу" outlined dense class="col-4" />
                <q-input v-model="form.discount_card" label="Дисконтная карта" outlined dense class="col-4" />
              </div>
              <q-select v-model="form.client_type" :options="types" option-value="id" option-label="name"
                emit-value map-options outlined dense clearable label="Тип клиента" />
              <q-select v-model="form.source" :options="sources" option-value="id" option-label="name"
                emit-value map-options outlined dense clearable label="Как нашли клинику" />
              <q-input v-model="form.passport" label="Паспорт (серия, номер)" outlined dense />
              <q-select v-if="form.id" v-model="form.status" :options="statusOptions" emit-value map-options
                outlined dense label="Статус" />
              <div><q-checkbox v-model="form.no_mailing" label="Отказ от рассылок (SMS, email)" dense /></div>
              <div><q-checkbox v-model="form.in_blacklist" label="В чёрном списке" color="negative" dense /></div>
              <q-input v-model="form.description" label="Описание" type="textarea" autogrow outlined dense />
            </div>
          </div>
          <div v-if="errors.non_field_errors" class="text-negative q-mt-sm">{{ errors.non_field_errors }}</div>
        </q-card-section>

        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Форма клиента: создание и изменение. Пока вводится ФИО и телефон, справа сверху
// появляются возможные дубли — чтобы не завести одного человека дважды.
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors, existingByName } from '@/api'
import { PHONE_KINDS, STATUS } from './statuses'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  client: { type: Object, default: null }, // null — новый клиент
})
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()
const router = useRouter()

const statusOptions = Object.entries(STATUS).map(([value, s]) => ({ value, label: s.label }))
const EMPTY = {
  last_name: '', first_name: '', middle_name: '', phones: [{ number: '', kind: 'mobile', is_primary: true }],
  city: null, street: null, house: '', zip_code: '', email: '', passport: '', discount_percent: 0,
  journal_number: '', discount_card: '', client_type: null, source: null, no_mailing: false,
  in_blacklist: false, description: '', status: 'active',
}
const form = ref({ ...EMPTY })
const errors = ref({})
const saving = ref(false)
const duplicates = ref([])

// --- справочники ---
const allCities = ref([])
const cities = ref([])
const allStreets = ref([])
const streets = ref([])
const types = ref([])
const sources = ref([])

async function loadDirectories() {
  const [c, t, s] = await Promise.all([
    apiGet('clients/cities/?active=true'),
    apiGet('clients/client-types/?active=true'),
    apiGet('clients/client-sources/?active=true'),
  ])
  allCities.value = cities.value = c.data ?? []
  types.value = t.data ?? []
  sources.value = s.data ?? []
}

async function loadStreets(cityId) {
  allStreets.value = streets.value = cityId ? ((await apiGet(`clients/streets/?active=true&city=${cityId}`)).data ?? []) : []
}

const byName = (list, text) => list.filter((item) => item.name.toLowerCase().includes(text.toLowerCase()))
const filterCities = (text, update) => update(() => (cities.value = byName(allCities.value, text)))
const filterStreets = (text, update) => update(() => (streets.value = byName(allStreets.value, text)))

// Новый город или улицу можно добавить прямо из формы — как в VetManager.
async function addCity(name, done) {
  const existing = existingByName(allCities.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('clients/cities/', { name })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить город' })
  allCities.value = cities.value = [...allCities.value, data].sort((a, b) => a.name.localeCompare(b.name))
  done(data.id, 'add-unique')
}

async function addStreet(name, done) {
  const existing = existingByName(allStreets.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('clients/streets/', { name, city: form.value.city })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить улицу' })
  allStreets.value = streets.value = [...allStreets.value, data].sort((a, b) => a.name.localeCompare(b.name))
  done(data.id, 'add-unique')
}

watch(() => form.value.city, (cityId) => loadStreets(cityId))

// --- открытие формы ---
watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    errors.value = {}
    duplicates.value = []
    form.value = props.client
      ? { ...props.client, phones: props.client.phones.map((p) => ({ ...p })) }
      : structuredClone(EMPTY)
    await loadDirectories()
  },
)

function makePrimary(index) {
  form.value.phones.forEach((phone, i) => (phone.is_primary = i === index))
}

// --- поиск дублей при вводе ---
let timer = null
watch(
  () => [form.value.last_name, form.value.first_name, form.value.middle_name, form.value.phones.map((p) => p.number).join('|')],
  () => {
    clearTimeout(timer)
    timer = setTimeout(checkDuplicates, 500)
  },
)

async function checkDuplicates() {
  const params = new URLSearchParams()
  for (const field of ['last_name', 'first_name', 'middle_name']) params.set(field, form.value[field] || '')
  for (const phone of form.value.phones) if (phone.number.replace(/\D/g, '').length >= 5) params.append('phone', phone.number)
  if (form.value.id) params.set('exclude', form.value.id)
  if ((form.value.last_name || '').trim().length < 2 && !params.has('phone')) {
    duplicates.value = []
    return
  }
  const { ok, data } = await apiGet(`clients/clients/duplicates/?${params}`)
  duplicates.value = ok ? data : []
}

function openDuplicate(id) {
  emit('update:modelValue', false)
  router.push(`/clients/${id}`)
}

// --- сохранение ---
async function save() {
  errors.value = {}
  saving.value = true
  const body = { ...form.value, phones: form.value.phones.filter((p) => p.number.trim()) }
  const { ok, data } = form.value.id
    ? await apiPatch(`clients/clients/${form.value.id}/`, body)
    : await apiPost('clients/clients/', body)
  saving.value = false
  if (!ok) {
    errors.value = fieldErrors(data)
    return
  }
  emit('update:modelValue', false)
  emit('saved', data)
  $q.notify({ type: 'positive', message: 'Клиент сохранён' })
}
</script>
