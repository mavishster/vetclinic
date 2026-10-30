<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Профилактика</h1>
      <q-btn outline color="primary" icon="download" label="Выгрузить в Excel" :href="exportUrl" />
    </div>

    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-btn-toggle v-model="mode" no-caps unelevated toggle-color="primary" class="col-auto" @update:model-value="load"
        :options="[{ label: 'Проведено', value: 'done' }, { label: 'Предстоит', value: 'due' }, { label: 'Просрочено', value: 'overdue' }]" />
      <template v-if="mode !== 'overdue'">
        <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-md-2" @update:model-value="load" />
        <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-md-2" @update:model-value="load" />
      </template>
      <q-select v-model="type" :options="types" option-value="id" option-label="name" emit-value map-options dense outlined
        clearable label="Процедура" class="col-6 col-md-2" @update:model-value="load" />
      <q-select v-model="species" :options="speciesList" option-value="id" option-label="name" emit-value map-options dense
        outlined clearable label="Вид животного" class="col-6 col-md-2" @update:model-value="load" />
    </div>
    <div class="text-caption text-grey-7 q-mb-sm">{{ HINTS[mode] }}</div>

    <q-table :rows="rows" :columns="columns" row-key="id" flat bordered :loading="loading" :pagination="{ rowsPerPage: 50 }"
      no-data-label="Ничего не найдено" rows-per-page-label="Строк на странице">
      <template #body-cell-pet_name="props">
        <q-td :props="props"><router-link :to="`/pets/${props.row.pet}`" class="text-primary">{{ props.row.pet_name }}</router-link></q-td>
      </template>
      <template #body-cell-client="props">
        <q-td :props="props">
          <router-link :to="`/clients/${props.row.client_id}`" class="text-primary">{{ props.row.client }}</router-link>
          <div v-if="props.row.phone" class="text-caption"><a :href="`tel:${props.row.phone}`">{{ props.row.phone }}</a></div>
        </q-td>
      </template>
    </q-table>
    <div class="text-caption text-grey-7 q-mt-sm">Всего: {{ rows.length }}</div>
  </q-page>
</template>

<script setup>
// Отчёт по профилактике: что проведено, у кого подходит срок, что просрочено — для обзвона.
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api'

const HINTS = {
  done: 'Процедуры, проведённые за период.',
  due: 'У кого срок следующей процедуры наступает в периоде — кому напомнить.',
  overdue: 'Срок повтора уже прошёл, а новой процедуры нет.',
}
const today = new Date()
const iso = (d) => d.toISOString().slice(0, 10)
const mode = ref('done')
const from = ref(iso(new Date(today.getFullYear(), today.getMonth(), 1)))
const to = ref(iso(today))
const type = ref(null)
const species = ref(null)
const types = ref([])
const speciesList = ref([])
const rows = ref([])
const loading = ref(false)
const fmt = (value) => (value ? new Date(value).toLocaleDateString('ru-RU') : '')
const columns = [
  { name: 'date', label: 'Дата', field: (r) => fmt(r.date), align: 'left' },
  { name: 'next_date', label: 'Следующая', field: (r) => fmt(r.next_date), align: 'left' },
  { name: 'type', label: 'Процедура', field: 'type', align: 'left' },
  { name: 'item', label: 'Препарат / услуга', field: 'item', align: 'left' },
  { name: 'pet_name', label: 'Питомец', field: 'pet_name', align: 'left' },
  { name: 'species', label: 'Вид', field: 'species', align: 'left' },
  { name: 'client', label: 'Владелец', field: 'client', align: 'left' },
  { name: 'doctor', label: 'Врач', field: 'doctor', align: 'left' },
]

const query = computed(() => {
  const params = new URLSearchParams({ mode: mode.value, from: from.value, to: to.value })
  if (type.value) params.set('type', type.value)
  if (species.value) params.set('species', species.value)
  return params
})
const exportUrl = computed(() => `/api/medical/preventions/report/?${query.value}&export=xlsx`)

async function load() {
  loading.value = true
  rows.value = (await apiGet(`medical/preventions/report/?${query.value}`)).data ?? []
  loading.value = false
}

onMounted(async () => {
  const [t, s] = await Promise.all([apiGet('medical/prevention-types/?active=true'), apiGet('clients/species/?active=true')])
  types.value = t.data ?? []
  speciesList.value = s.data ?? []
  load()
})
</script>
