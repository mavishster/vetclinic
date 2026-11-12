<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.sm" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 620px; max-width: 96vw">
      <q-form @submit="save()">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ title }}</div>
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none q-gutter-y-sm">
          <template v-if="!form.id && !fixedClient">
            <q-btn-toggle v-model="clientMode" no-caps unelevated dense toggle-color="primary" spread
              :options="[{ label: 'Клиент из базы', value: 'existing' }, { label: 'Новый клиент', value: 'new' }]" />
            <ClientSelect v-if="clientMode === 'existing'" v-model="form.client" label="Клиент *"
              @update:model-value="loadPets" />
            <template v-else>
              <div class="row q-col-gutter-sm">
                <q-input v-model="quick.last_name" label="Фамилия *" outlined dense class="col-6" />
                <q-input v-model="quick.first_name" label="Имя" outlined dense class="col-6" />
                <q-input v-model="quick.phone" label="Телефон" outlined dense inputmode="tel" class="col-12" />
              </div>
              <q-banner v-if="duplicates.length" dense rounded class="bg-amber-1 text-dark">
                Возможно, клиент уже есть:
                <div v-for="dup in duplicates" :key="dup.id">
                  {{ dup.full_name }} · {{ dup.phones.join(', ') }}
                  <q-btn flat dense no-caps color="primary" label="Выбрать" @click="useDuplicate(dup)" />
                </div>
              </q-banner>
              <div class="text-caption text-grey-7">Клиент будет временным — полную карточку заполните, когда он придёт.</div>
            </template>
          </template>
          <div v-else class="text-subtitle2">{{ clientName }}</div>

          <q-select v-if="pets.length" v-model="form.pet" :options="pets" option-value="id" option-label="label"
            emit-value map-options outlined dense clearable label="Питомец" />
          <q-input v-if="!form.pet" v-model="form.pet_note" label="Питомец со слов (кличка, вид)" outlined dense />

          <div class="row q-col-gutter-sm">
            <q-select v-model="form.purpose" :options="purposes" option-value="id" option-label="name" emit-value
              map-options outlined dense clearable label="Цель" class="col-12 col-sm-6" @update:model-value="onPurpose" />
            <q-select v-model="form.doctor" :options="doctors" option-value="id" option-label="name" emit-value
              map-options outlined dense clearable label="Врач" class="col-12 col-sm-6" />
          </div>
          <div v-if="!walkIn" class="row q-col-gutter-sm">
            <q-input v-model="form.date" type="date" label="Дата" stack-label outlined dense class="col-5" />
            <q-input v-model="form.time" type="time" step="300" label="Время" stack-label outlined dense class="col-3" />
            <q-select v-model="form.minutes" :options="DURATIONS" emit-value map-options outlined dense label="Длительность"
              class="col-4" />
          </div>
          <q-input v-model="form.note" label="Заметка для врача" type="textarea" autogrow outlined dense />

          <q-banner v-if="warnings.length" rounded class="banner-warning">
            <template #avatar><q-icon name="warning" color="warning" /></template>
            <div v-for="w in warnings" :key="w">{{ w }}</div>
          </q-banner>
          <div v-if="error" class="text-negative">{{ error }}</div>
        </q-card-section>

        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn v-if="warnings.length" color="warning" unelevated label="Записать всё равно" :loading="saving"
            @click="save(true)" />
          <q-btn v-else type="submit" color="primary" unelevated :label="walkIn ? 'В очередь' : 'Записать'" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Запись на приём: клиент из базы или новый (временный), питомец, цель, врач, время.
// Если сервер предупреждает (врач занят, не в графике…) — показываем и даём «записать всё равно».
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import ClientSelect from '@/modules/clients/ClientSelect.vue'
import { isoDate } from './appointments'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  appointment: { type: Object, default: null }, // изменение существующей записи
  preset: { type: Object, default: () => ({}) }, // { start: Date, doctor, client, clientName }
  doctors: { type: Array, default: () => [] }, // [{ id, name }]
  walkIn: { type: Boolean, default: false }, // клиент без записи — сразу в очередь
})
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()
const DURATIONS = [10, 15, 20, 30, 45, 60, 90, 120].map((m) => ({ value: m, label: `${m} мин` }))
const pad = (n) => String(n).padStart(2, '0')

const form = ref({})
const quick = ref({ last_name: '', first_name: '', phone: '' })
const clientMode = ref('existing')
const pets = ref([])
const purposes = ref([])
const duplicates = ref([])
const warnings = ref([])
const error = ref('')
const saving = ref(false)

const fixedClient = computed(() => Boolean(props.preset.client))
const clientName = computed(() => props.appointment?.client_name || props.preset.clientName || '')
const title = computed(() => (form.value.id ? 'Запись на приём' : props.walkIn ? 'Клиент без записи' : 'Новая запись'))

async function loadPets(clientId) {
  form.value.pet = null
  if (!clientId) return (pets.value = [])
  const { data } = await apiGet(`clients/pets/?owner=${clientId}&status=active&page_size=100`)
  pets.value = (data?.results ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.species_name}, ${p.breed_name})` }))
  if (pets.value.length === 1) form.value.pet = pets.value[0].id
}

function onPurpose(id) {
  const purpose = purposes.value.find((p) => p.id === id)
  if (purpose) form.value.minutes = purpose.duration_minutes
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    warnings.value = []
    error.value = ''
    duplicates.value = []
    clientMode.value = 'existing'
    quick.value = { last_name: '', first_name: '', phone: '' }
    purposes.value = (await apiGet('scheduling/purposes/?active=true')).data ?? []
    const a = props.appointment
    const start = a ? new Date(a.start) : props.preset.start || new Date()
    const minutes = a ? Math.round((new Date(a.end) - new Date(a.start)) / 60000) : 30
    form.value = {
      id: a?.id, client: a?.client ?? props.preset.client ?? null, pet: a?.pet ?? null, pet_note: a?.pet_note ?? '',
      purpose: a?.purpose ?? null, doctor: a?.doctor ?? props.preset.doctor ?? null, note: a?.note ?? '',
      date: isoDate(start), time: `${pad(start.getHours())}:${pad(start.getMinutes())}`, minutes,
    }
    if (form.value.client) {
      const pet = form.value.pet
      await loadPets(form.value.client)
      if (pet) form.value.pet = pet
    } else pets.value = []
  },
)

// Поменяли что-то после предупреждения — проверим заново при сохранении.
watch(form, () => (warnings.value = []), { deep: true })

// Проверка дублей при вводе нового клиента: по телефону и фамилии.
let timer = null
watch(
  () => [quick.value.last_name, quick.value.phone],
  () => {
    clearTimeout(timer)
    timer = setTimeout(async () => {
      const params = new URLSearchParams({ last_name: quick.value.last_name, first_name: quick.value.first_name })
      if (quick.value.phone.replace(/\D/g, '').length >= 5) params.append('phone', quick.value.phone)
      if (quick.value.last_name.trim().length < 2 && !params.has('phone')) return (duplicates.value = [])
      duplicates.value = (await apiGet(`clients/clients/duplicates/?${params}`)).data ?? []
    }, 500)
  },
)

function useDuplicate(dup) {
  clientMode.value = 'existing'
  form.value.client = dup.id
  loadPets(dup.id)
}

async function save(force = false) {
  error.value = ''
  saving.value = true
  const start = new Date(`${form.value.date}T${form.value.time}`)
  const body = {
    pet: form.value.pet, pet_note: form.value.pet ? '' : form.value.pet_note, purpose: form.value.purpose,
    doctor: form.value.doctor, note: form.value.note,
    start: start.toISOString(), end: new Date(start.getTime() + form.value.minutes * 60000).toISOString(),
  }
  if (!form.value.id) {
    if (clientMode.value === 'new' && !fixedClient.value) body.new_client = quick.value
    else body.client = form.value.client
  }
  const query = force ? '?force=1' : ''
  const { ok, status, data } = form.value.id
    ? await apiPatch(`scheduling/appointments/${form.value.id}/${query}`, body)
    : props.walkIn
      ? await apiPost('scheduling/appointments/walk-in/', body)
      : await apiPost(`scheduling/appointments/${query}`, body)
  saving.value = false
  if (status === 409) {
    warnings.value = data.warnings
    return
  }
  if (!ok) {
    error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить запись'
    return
  }
  emit('update:modelValue', false)
  emit('saved', data)
  $q.notify({ type: 'positive', message: props.walkIn ? 'Клиент в очереди' : 'Запись сохранена' })
}
</script>
