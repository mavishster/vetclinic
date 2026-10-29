<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Питомцы</h1>
      <q-btn v-if="can('clients.add_pet')" color="primary" icon="add" label="Новый питомец" unelevated
        @click="editorOpen = true" />
    </div>

    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" autofocus
        placeholder="Кличка, № чипа, лаб. №, фамилия владельца" class="col-12 col-md-5" @update:model-value="reload">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-select v-model="speciesId" :options="species" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Вид" class="col-6 col-md-2" @update:model-value="reload" />
      <q-btn-toggle v-model="status" no-caps unelevated toggle-color="primary" class="col-auto"
        :options="[{ label: 'Живые', value: 'active' }, { label: 'Умершие', value: 'dead' }, { label: 'Все', value: '' }]"
        @update:model-value="reload" />
    </div>

    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading"
      flat bordered :rows-per-page-options="[25, 50, 100]" no-data-label="Питомцы не найдены"
      rows-per-page-label="Строк на странице" @request="onRequest" @row-click="(e, row) => open(row)" />

    <PetEditDialog v-model="editorOpen" @saved="open" />
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api'
import { can } from '@/session'
import PetEditDialog from './PetEditDialog.vue'
import { ageText, SEX } from './pets'

const router = useRouter()
const rows = ref([])
const loading = ref(false)
const search = ref('')
const speciesId = ref(null)
const status = ref('active')
const species = ref([])
const editorOpen = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })

const columns = [
  { name: 'name', label: 'Кличка', field: 'name', align: 'left', classes: 'text-weight-medium' },
  { name: 'kind', label: 'Вид, порода', field: (p) => `${p.species_name}, ${p.breed_name}`, align: 'left' },
  { name: 'sex', label: 'Пол', field: (p) => SEX.find((s) => s.value === p.sex)?.short, align: 'center' },
  { name: 'age', label: 'Возраст', field: (p) => (p.status === 'dead' ? 'умер' : ageText(p)), align: 'left' },
  { name: 'owner', label: 'Владелец', field: 'owner_name', align: 'left' },
  { name: 'chip', label: '№ чипа', field: 'chip_number', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  if (search.value) params.set('search', search.value)
  if (speciesId.value) params.set('species', speciesId.value)
  if (status.value) params.set('status', status.value)
  const { ok, data } = await apiGet(`clients/pets/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}

const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
const open = (pet) => router.push(`/pets/${pet.id}`)

onMounted(async () => {
  species.value = (await apiGet('clients/species/?active=true')).data ?? []
  reload()
})
</script>
