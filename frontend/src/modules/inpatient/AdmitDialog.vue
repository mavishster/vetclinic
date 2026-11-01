<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-form @submit="save">
        <q-card-section class="text-h6">Принять в стационар</q-card-section>
        <q-card-section class="q-pt-none q-gutter-y-sm">
          <template v-if="!preset.pet">
            <ClientSelect v-model="client" label="Клиент *" @update:model-value="loadPets" />
            <q-select v-model="form.pet" :options="pets" option-value="id" option-label="label" emit-value map-options outlined dense
              label="Питомец *" :disable="!client" />
          </template>
          <div v-else class="text-subtitle2">{{ preset.petName }}</div>
          <div class="row q-col-gutter-sm">
            <q-select v-model="form.ward" :options="wards" option-value="id" option-label="label" emit-value map-options outlined dense
              label="Палата *" class="col-8" />
            <q-input v-model.number="form.place" type="number" min="1" outlined dense label="Место" class="col-4" />
          </div>
          <q-select v-model="form.doctor" :options="doctors" option-value="id" option-label="name" emit-value map-options outlined dense
            label="Лечащий врач *" />
          <q-input v-model="form.reason" type="textarea" autogrow outlined dense label="Причина госпитализации, диагноз" />
          <q-input v-model="form.planned_discharge" type="date" stack-label outlined dense label="Плановая выписка" />
          <div v-if="error" class="text-negative">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn type="submit" color="primary" unelevated icon="local_hotel" label="Принять" :loading="saving"
            :disable="!form.pet || !form.ward || !form.doctor" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Приём в стационар: питомец (или из медкарты), палата со свободными местами, врач, причина.
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { session } from '@/session'
import ClientSelect from '@/modules/clients/ClientSelect.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  preset: { type: Object, default: () => ({}) }, // { pet, petName, visit, doctor } — из медкарты
})
const emit = defineEmits(['update:modelValue'])
const router = useRouter()
const client = ref(null)
const pets = ref([])
const wards = ref([])
const doctors = ref([])
const form = ref({})
const error = ref('')
const saving = ref(false)

async function loadPets(clientId) {
  form.value.pet = null
  const { data } = await apiGet(`clients/pets/?owner=${clientId}&status=active&page_size=100`)
  pets.value = (data?.results ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.species_name})` }))
  if (pets.value.length === 1) form.value.pet = pets.value[0].id
}

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  client.value = null
  form.value = { pet: props.preset.pet || null, visit: props.preset.visit || null, ward: null, place: null,
    doctor: props.preset.doctor || session.user?.id, reason: '', planned_discharge: null }
  const [w, board, d] = await Promise.all([apiGet('inpatient/wards/?active=true'), apiGet('inpatient/hospitalizations/'), apiGet('medical/visits/doctors/')])
  const busy = {}
  for (const h of board.data ?? []) busy[h.ward] = (busy[h.ward] || 0) + 1
  wards.value = (w.data ?? []).map((x) => ({ ...x, label: `${x.name} — свободно ${Math.max(x.places - (busy[x.id] || 0), 0)} из ${x.places}` }))
  doctors.value = d.data ?? []
}, { immediate: true })

async function save() {
  error.value = ''
  saving.value = true
  const { ok, data } = await apiPost('inpatient/hospitalizations/', { ...form.value, place: form.value.place || null, planned_discharge: form.value.planned_discharge || null })
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось принять')
  emit('update:modelValue', false)
  router.push(`/inpatient/${data.id}`)
}
</script>
