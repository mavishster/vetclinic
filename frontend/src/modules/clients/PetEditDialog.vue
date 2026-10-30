<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.sm" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 640px; max-width: 96vw">
      <q-form @submit="save">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ form.id ? 'Изменить питомца' : 'Новый питомец' }}</div>
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none q-gutter-y-sm">
          <div v-if="!form.id && !ownerId">
            <ClientSelect v-model="form.owner" label="Владелец *" />
          </div>
          <div v-else-if="!form.id" class="text-grey-8">Владелец: {{ ownerName }}</div>

          <q-input v-model="form.name" label="Кличка *" outlined dense autofocus />
          <div class="row q-col-gutter-sm">
            <q-select v-model="form.species" :options="species" option-value="id" option-label="name" emit-value
              map-options outlined dense label="Вид *" class="col-12 col-sm-6" @update:model-value="onSpecies" />
            <q-select v-model="form.breed" :options="breeds" option-value="id" option-label="name" emit-value
              map-options outlined dense use-input input-debounce="0" new-value-mode="add-unique"
              :disable="!form.species" label="Порода *" class="col-12 col-sm-6"
              hint="Нет в списке — впишите и нажмите Enter" @filter="filterBreeds" @new-value="addBreed" />
          </div>
          <div class="row q-col-gutter-sm items-center">
            <div class="col-12 col-sm-7">
              <q-btn-toggle v-model="form.sex" :options="SEX.map((s) => ({ label: s.label, value: s.value }))"
                no-caps unelevated toggle-color="primary" spread />
            </div>
            <div class="col-12 col-sm-5">
              <q-checkbox v-model="form.sterilized" label="Стерилизован(а) / кастрирован" dense />
            </div>
          </div>
          <q-select v-model="form.color" :options="colors" option-value="id" option-label="name" emit-value
            map-options outlined dense clearable use-input input-debounce="0" new-value-mode="add-unique"
            label="Окрас" @filter="filterColors" @new-value="addColor" />

          <div class="text-subtitle2 text-grey-8 q-pt-sm">Возраст</div>
          <q-btn-toggle v-model="ageMode" no-caps unelevated toggle-color="primary" dense
            :options="[{ label: 'Знаю дату рождения', value: 'date' }, { label: 'Знаю только возраст', value: 'age' }]" />
          <q-input v-if="ageMode === 'date'" v-model="form.birth_date" type="date" outlined dense label="Дата рождения"
            :max="today" stack-label />
          <div v-else class="row q-col-gutter-sm">
            <q-input v-model.number="ageYears" type="number" min="0" outlined dense label="Лет" class="col-6" />
            <q-input v-model.number="ageMonths" type="number" min="0" max="11" outlined dense label="Месяцев" class="col-6" />
          </div>

          <div class="row q-col-gutter-sm">
            <q-input v-model="form.chip_number" label="№ чипа" outlined dense class="col-7" />
            <q-input v-model="form.lab_number" label="Лабораторный №" outlined dense class="col-5" />
          </div>
          <q-input v-model="form.notes" label="Примечание" type="textarea" autogrow outlined dense />
          <div v-if="errors.non_field_errors" class="text-negative">{{ errors.non_field_errors }}</div>
          <div v-for="field in ['owner', 'name', 'species', 'breed']" :key="field">
            <div v-if="errors[field]" class="text-negative">{{ fieldTitles[field] }}: {{ errors[field] }}</div>
          </div>
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
import { ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors, existingByName } from '@/api'
import ClientSelect from './ClientSelect.vue'
import { birthDateFromAge, SEX } from './pets'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  pet: { type: Object, default: null }, // null — новый питомец
  ownerId: { type: String, default: null }, // заранее выбранный владелец (из карточки клиента)
  ownerName: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()
const today = new Date().toISOString().slice(0, 10)
const fieldTitles = { owner: 'Владелец', name: 'Кличка', species: 'Вид', breed: 'Порода' }

const EMPTY = {
  owner: null, name: '', species: null, breed: null, sex: 'unknown', sterilized: false, color: null,
  birth_date: null, birth_date_approximate: false, chip_number: '', lab_number: '', notes: '',
}
const form = ref({ ...EMPTY })
const errors = ref({})
const saving = ref(false)
const ageMode = ref('date')
const ageYears = ref(null)
const ageMonths = ref(null)

const species = ref([])
const allBreeds = ref([])
const breeds = ref([])
const allColors = ref([])
const colors = ref([])

const byName = (list, text) => list.filter((i) => i.name.toLowerCase().includes(text.toLowerCase()))
const filterBreeds = (text, update) => update(() => (breeds.value = byName(allBreeds.value, text)))
const filterColors = (text, update) => update(() => (colors.value = byName(allColors.value, text)))

async function loadBreeds(speciesId) {
  allBreeds.value = breeds.value = speciesId
    ? ((await apiGet(`clients/breeds/?active=true&species=${speciesId}`)).data ?? [])
    : []
}

async function onSpecies(speciesId) {
  form.value.breed = null
  await loadBreeds(speciesId)
}

async function addBreed(name, done) {
  const existing = existingByName(allBreeds.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('clients/breeds/', { name, species: form.value.species })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить породу' })
  allBreeds.value = breeds.value = [...allBreeds.value, data]
  done(data.id, 'add-unique')
}

async function addColor(name, done) {
  const existing = existingByName(allColors.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('clients/colors/', { name })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить окрас' })
  allColors.value = colors.value = [...allColors.value, data]
  done(data.id, 'add-unique')
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    errors.value = {}
    form.value = props.pet ? { ...props.pet } : { ...EMPTY, owner: props.ownerId }
    ageMode.value = form.value.birth_date_approximate ? 'age' : 'date'
    ageYears.value = ageMonths.value = null
    const [s, c] = await Promise.all([apiGet('clients/species/?active=true'), apiGet('clients/colors/?active=true')])
    species.value = s.data ?? []
    allColors.value = colors.value = c.data ?? []
    await loadBreeds(form.value.species)
  },
)

async function save() {
  errors.value = {}
  const body = { ...form.value }
  if (ageMode.value === 'age') {
    if (ageYears.value || ageMonths.value) {
      body.birth_date = birthDateFromAge(ageYears.value, ageMonths.value)
      body.birth_date_approximate = true
    }
  } else {
    body.birth_date = body.birth_date || null
    body.birth_date_approximate = false
  }
  for (const key of ['weight', 'owner_name', 'species_name', 'breed_name', 'color_name']) delete body[key]
  saving.value = true
  const { ok, data } = form.value.id
    ? await apiPatch(`clients/pets/${form.value.id}/`, body)
    : await apiPost('clients/pets/', body)
  saving.value = false
  if (!ok) {
    errors.value = fieldErrors(data)
    return
  }
  emit('update:modelValue', false)
  emit('saved', data)
  $q.notify({ type: 'positive', message: 'Питомец сохранён' })
}
</script>
