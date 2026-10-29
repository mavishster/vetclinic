<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Медкарта</h1>
    </div>
    <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Кличка или фамилия владельца"
      class="q-mb-md" style="max-width: 420px" @update:model-value="reload">
      <template #prepend><q-icon name="search" /></template>
    </q-input>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading" flat bordered
      :rows-per-page-options="[25, 50, 100]" no-data-label="Записей нет" rows-per-page-label="Строк на странице"
      @request="onRequest" @row-click="(e, row) => $router.push(`/visits/${row.id}`)" />
    <div class="text-caption text-grey-7 q-mt-sm">Новая запись создаётся из карточки питомца или из записи на приём.</div>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = [
  { name: 'date', label: 'Дата', field: (v) => new Date(v.date).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }), align: 'left' },
  { name: 'pet', label: 'Питомец', field: 'pet_name', align: 'left', classes: 'text-weight-medium' },
  { name: 'client', label: 'Владелец', field: 'client_name', align: 'left' },
  { name: 'purpose', label: 'Цель', field: 'purpose_name', align: 'left' },
  { name: 'diagnoses', label: 'Диагнозы', field: (v) => v.diagnoses.map((d) => d.name).join(', '), align: 'left' },
  { name: 'doctor', label: 'Врач', field: 'doctor_name', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  if (search.value) params.set('search', search.value)
  const { ok, data } = await apiGet(`medical/visits/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}
const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
onMounted(reload)
</script>
