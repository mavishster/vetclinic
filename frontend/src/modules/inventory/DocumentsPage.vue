<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Документы склада</h1>
      <template v-if="can('inventory.add_stockdocument')">
        <q-btn v-for="(kind, code) in DOC_KINDS" :key="code" :color="kind.color" unelevated :icon="kind.icon"
          :label="kind.label" @click="$router.push(`/inventory/documents/new?kind=${code}`)" />
      </template>
    </div>
    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Номер, поставщик, № накладной"
        class="col-12 col-md-4" @update:model-value="reload"><template #prepend><q-icon name="search" /></template></q-input>
      <q-btn-toggle v-model="kind" no-caps unelevated toggle-color="primary" @update:model-value="reload"
        :options="[{ label: 'Все', value: '' }, ...Object.entries(DOC_KINDS).map(([value, k]) => ({ label: k.label, value }))]" />
      <q-btn-toggle v-model="status" no-caps unelevated toggle-color="primary" @update:model-value="reload"
        :options="[{ label: 'Любые', value: '' }, { label: 'Черновики', value: 'draft' }, { label: 'Выполненные', value: 'executed' }]" />
    </div>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading" flat bordered
      :rows-per-page-options="[25, 50, 100]" no-data-label="Документов нет" rows-per-page-label="Строк на странице"
      @request="onRequest" @row-click="(e, row) => $router.push(`/inventory/documents/${row.id}`)">
      <template #body-cell-kind="props">
        <q-td :props="props"><q-icon :name="DOC_KINDS[props.row.kind].icon" :color="DOC_KINDS[props.row.kind].color" class="q-mr-xs" />{{ props.row.kind_label }}</q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props"><q-badge :color="props.row.status === 'executed' ? 'positive' : 'grey-6'" :label="props.row.status_label" /></q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import { DOC_KINDS } from './routes'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const kind = ref('')
const status = ref('')
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = [
  { name: 'number', label: '№', field: 'number', align: 'left', classes: 'text-weight-medium' },
  { name: 'date', label: 'Дата', field: (d) => new Date(d.date).toLocaleDateString('ru-RU'), align: 'left' },
  { name: 'kind', label: 'Вид', field: 'kind_label', align: 'left' },
  { name: 'where', label: 'Склад', field: (d) => (d.target_warehouse_name ? `${d.warehouse_name} → ${d.target_warehouse_name}` : d.warehouse_name), align: 'left' },
  { name: 'who', label: 'Поставщик / причина', field: (d) => d.counterparty_name || d.reason, align: 'left' },
  { name: 'total', label: 'Сумма', field: (d) => (d.total ? money(d.total) : ''), align: 'right' },
  { name: 'status', label: 'Статус', field: 'status', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  if (search.value) params.set('search', search.value)
  if (kind.value) params.set('kind', kind.value)
  if (status.value) params.set('status', status.value)
  const { ok, data } = await apiGet(`inventory/documents/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}
const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
onMounted(reload)
</script>
