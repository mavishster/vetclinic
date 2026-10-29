<template>
  <q-page padding>
    <div v-if="!pet" class="flex flex-center q-pa-xl">
      <q-spinner v-if="loading" size="40px" color="primary" />
      <div v-else class="text-grey-7">Питомец не найден.</div>
    </div>

    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" @click="$router.back()" />
        <h1 class="text-h5 q-my-none">{{ pet.name }}</h1>
        <q-badge v-if="pet.status === 'dead'" color="grey-7" :label="`умер ${formatDate(pet.death_date)}`" />
        <q-space />
        <template v-if="can('clients.change_pet')">
          <q-btn outline color="primary" icon="edit" label="Изменить" @click="editorOpen = true" />
          <q-btn flat icon="swap_horiz" label="Сменить владельца" @click="transferOpen = true" />
          <q-btn v-if="pet.status === 'active'" flat icon="sentiment_dissatisfied" label="Питомец умер" @click="markDead" />
          <q-btn v-else flat icon="undo" label="Отменить отметку о смерти" @click="revive" />
        </template>
        <q-btn v-if="can('clients.delete_pet')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
      </div>

      <div class="row q-col-gutter-md">
        <div class="col-12 col-md-6">
          <q-card flat bordered>
            <q-list dense>
              <q-item clickable :to="`/clients/${pet.owner}`">
                <q-item-section avatar><q-icon name="person" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label class="text-primary">{{ pet.owner_name }}</q-item-label>
                  <q-item-label caption>Владелец</q-item-label>
                </q-item-section>
              </q-item>
              <q-separator spaced />
              <q-item v-for="row in details" :key="row.label">
                <q-item-section class="text-grey-7 col-5">{{ row.label }}</q-item-section>
                <q-item-section>{{ row.value }}</q-item-section>
              </q-item>
            </q-list>
            <q-card-section v-if="pet.notes" class="text-body2" style="white-space: pre-line">{{ pet.notes }}</q-card-section>
          </q-card>
        </div>

        <div class="col-12 col-md-6">
          <q-card flat bordered>
            <q-card-section class="text-subtitle1">Вес</q-card-section>
            <q-card-section v-if="can('clients.change_pet')" class="q-pt-none">
              <q-form class="row q-col-gutter-sm items-start" @submit="addWeight">
                <q-input v-model="newWeight" type="number" step="0.001" min="0" outlined dense label="Вес, кг"
                  class="col-5" :error="!!weightError" :error-message="weightError" />
                <q-input v-model="newWeightDate" type="date" outlined dense label="Дата" stack-label :max="today" class="col-5" />
                <div class="col-2"><q-btn type="submit" color="primary" unelevated icon="add" class="full-width" /></div>
              </q-form>
            </q-card-section>
            <q-list dense separator>
              <q-item v-for="w in weights" :key="w.id">
                <q-item-section>{{ Number(w.weight) }} кг</q-item-section>
                <q-item-section side>{{ formatDate(w.date) }}</q-item-section>
              </q-item>
              <q-item v-if="!weights.length">
                <q-item-section class="text-grey-7">Взвешиваний пока нет</q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>
      </div>

      <PetEditDialog v-model="editorOpen" :pet="pet" @saved="(data) => (pet = data)" />

      <q-dialog v-model="transferOpen">
        <q-card style="width: 480px; max-width: 95vw">
          <q-card-section class="text-h6">Передать другому владельцу</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <ClientSelect v-model="newOwner" label="Новый владелец" />
            <div class="text-caption text-grey-7">
              Медкарта уйдёт вместе с питомцем, а счета останутся у прежнего владельца.
              У прежнего владельца питомец будет виден в «бывших».
            </div>
            <div v-if="transferError" class="text-negative">{{ transferError }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn color="primary" unelevated label="Передать" :disable="!newOwner" @click="transfer" />
          </q-card-actions>
        </q-card>
      </q-dialog>
    </template>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import ClientSelect from './ClientSelect.vue'
import PetEditDialog from './PetEditDialog.vue'
import { ageText, formatDate, sexLabel } from './pets'

const props = defineProps({ id: { type: String, required: true } })
const $q = useQuasar()
const router = useRouter()
const today = new Date().toISOString().slice(0, 10)
const pet = ref(null)
const loading = ref(true)
const weights = ref([])
const editorOpen = ref(false)
const transferOpen = ref(false)
const newOwner = ref(null)
const transferError = ref('')
const newWeight = ref('')
const newWeightDate = ref(today)
const weightError = ref('')

const details = computed(() =>
  [
    { label: 'Вид, порода', value: `${pet.value.species_name}, ${pet.value.breed_name}` },
    { label: 'Пол', value: [sexLabel(pet.value), pet.value.sterilized ? 'стерилизован(а)' : ''].filter(Boolean).join(', ') },
    { label: 'Возраст', value: ageText(pet.value) },
    { label: 'Дата рождения', value: pet.value.birth_date ? `${formatDate(pet.value.birth_date)}${pet.value.birth_date_approximate ? ' (примерно)' : ''}` : '' },
    { label: 'Окрас', value: pet.value.color_name },
    { label: '№ чипа', value: pet.value.chip_number },
    { label: 'Лабораторный №', value: pet.value.lab_number },
  ].filter((row) => row.value),
)

async function load() {
  loading.value = true
  const [p, w] = await Promise.all([apiGet(`clients/pets/${props.id}/`), apiGet(`clients/pets/${props.id}/weights/`)])
  pet.value = p.ok ? p.data : null
  weights.value = w.ok ? w.data : []
  loading.value = false
}

async function addWeight() {
  weightError.value = ''
  const { ok, data } = await apiPost(`clients/pets/${pet.value.id}/weights/`, { weight: newWeight.value, date: newWeightDate.value })
  if (!ok) {
    const errors = fieldErrors(data)
    weightError.value = errors.weight || errors.non_field_errors || errors.date
    return
  }
  newWeight.value = ''
  load()
}

async function transfer() {
  transferError.value = ''
  const { ok, data } = await apiPost(`clients/pets/${pet.value.id}/transfer/`, { owner: newOwner.value })
  if (!ok) {
    transferError.value = fieldErrors(data).non_field_errors || 'Не удалось передать питомца'
    return
  }
  pet.value = data
  transferOpen.value = false
  newOwner.value = null
  $q.notify({ type: 'positive', message: `Питомец передан: ${data.owner_name}` })
}

function markDead() {
  $q.dialog({
    title: 'Отметить, что питомец умер?',
    message: 'Дата смерти — сегодня (можно изменить позже в карточке). Питомец исчезнет из напоминаний.',
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Отметить', color: 'primary', unelevated: true },
  }).onOk(async () => {
    const { ok, data } = await apiPost(`clients/pets/${pet.value.id}/death/`, {})
    if (ok) pet.value = data
  })
}

async function revive() {
  const { ok, data } = await apiPatch(`clients/pets/${pet.value.id}/`, { status: 'active' })
  if (ok) pet.value = data
}

function remove() {
  $q.dialog({
    title: 'Удалить питомца?',
    message: 'Удаляйте только ошибочно созданные карточки. Если питомец умер — отметьте это кнопкой «Питомец умер».',
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
    persistent: true,
  }).onOk(async () => {
    const owner = pet.value.owner
    const { ok } = await apiDelete(`clients/pets/${pet.value.id}/`)
    if (ok) router.push(`/clients/${owner}`)
  })
}

onMounted(load)
</script>
