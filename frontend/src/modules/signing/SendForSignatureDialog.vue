<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 460px; max-width: 95vw">
      <q-card-section class="text-h6">На подпись клиенту</q-card-section>
      <q-card-section v-if="!request" class="q-pt-none q-gutter-y-sm">
        <q-select v-model="form.template" :options="templates" option-value="id" option-label="name" emit-value map-options outlined
          dense label="Документ" @update:model-value="guessPurpose" />
        <q-select v-model="form.purpose" :options="PURPOSES" emit-value map-options outlined dense label="Что это за документ"
          :hint="form.purpose === 'consent' ? 'После подписи в карточке появится согласие и станет доступно фото' : ''" />
        <q-select v-if="stations.length > 1" v-model="form.station" :options="stations" option-value="id" option-label="name"
          emit-value map-options outlined dense label="На какой планшет" />
        <q-select v-if="form.purpose === 'contract' && contracts.length" v-model="form.contract" :options="contracts" option-value="id"
          option-label="label" emit-value map-options outlined dense clearable label="Договор (подписанный PDF станет его сканом)" />
        <div v-if="!stations.length" class="text-negative">Нет ни одного планшета подписи — добавьте его в «Справочники → Планшеты подписи».</div>
        <div v-if="error" class="text-negative">{{ error }}</div>
      </q-card-section>
      <q-card-section v-else class="q-pt-none text-center">
        <template v-if="request.status === 'pending'">
          <q-spinner-dots size="40px" color="primary" />
          <div class="q-mt-sm">Документ на планшете «{{ request.station_name }}». Ждём подпись клиента…</div>
        </template>
        <template v-else-if="request.status === 'signed'">
          <q-icon name="task_alt" color="positive" size="48px" />
          <div class="q-mt-sm text-subtitle1">Подписано</div>
          <q-btn flat no-caps color="primary" icon="picture_as_pdf" label="Открыть PDF" :href="`/api/core/attachments/${request.result}/download/`" target="_blank" />
        </template>
        <div v-else class="text-grey-7">Отменено</div>
      </q-card-section>
      <q-card-actions align="right">
        <template v-if="!request">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn color="primary" unelevated icon="tablet_mac" label="Отправить на планшет" :disable="!form.template || !form.station" @click="send" />
        </template>
        <template v-else-if="request.status === 'pending'">
          <q-btn flat color="negative" label="Отменить" @click="cancel" />
        </template>
        <q-btn v-else color="primary" unelevated label="Готово" @click="close" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Отправка документа клиенту на подпись на планшет; ждём подпись, показывая статус.
import { onUnmounted, ref, watch } from 'vue'
import { apiGet, apiPost, fieldErrors } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false }, client: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue', 'signed'])
const templates = ref([])
const stations = ref([])
const contracts = ref([])
const form = ref({})
const request = ref(null)
const error = ref('')
let timer = null

watch(() => props.modelValue, async (open) => {
  if (!open) return
  request.value = null
  error.value = ''
  const [t, s, c] = await Promise.all([
    apiGet('clients/signatures/templates/'), apiGet('clients/signing-stations/?active=true'),
    apiGet(`clients/contracts/?client=${props.client.id}`),
  ])
  templates.value = t.data ?? []
  stations.value = s.data ?? []
  contracts.value = (c.data?.results ?? c.data ?? []).map((x) => ({ id: x.id, label: `№ ${x.number} от ${new Date(x.date).toLocaleDateString('ru-RU')}` }))
  form.value = { template: null, station: stations.value[0]?.id ?? null, purpose: 'other', contract: null }
}, { immediate: true })

const PURPOSES = [
  { value: 'contract', label: 'Договор' },
  { value: 'consent', label: 'Согласие на обработку ПДн и фото' },
  { value: 'other', label: 'Другой документ (согласие на наркоз, операцию…)' },
]

// Подсказка по названию; согласием на ПДн и фото считается только документ о персональных данных,
// а не любое «согласие» (на наркоз, операцию). Выбор можно поправить вручную.
function guessPurpose(id) {
  const name = (templates.value.find((t) => t.id === id)?.name || '').toLowerCase()
  const personal = name.includes('пдн') || name.includes('персональн') || name.includes('фото')
  form.value.purpose = personal ? 'consent' : name.includes('договор') ? 'contract' : 'other'
}

async function send() {
  error.value = ''
  const { ok, data } = await apiPost('clients/signatures/', { client: props.client.id, ...form.value })
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось отправить')
  request.value = data
  timer = setInterval(check, 2000)
}
async function check() {
  const { ok, data } = await apiGet(`clients/signatures/${request.value.id}/`)
  if (!ok) return
  request.value = data
  if (data.status !== 'pending') {
    clearInterval(timer)
    if (data.status === 'signed') emit('signed', data)
  }
}
async function cancel() {
  await apiPost(`clients/signatures/${request.value.id}/cancel/`)
  check()
}
function close() {
  clearInterval(timer)
  emit('update:modelValue', false)
}
onUnmounted(() => clearInterval(timer))
</script>
