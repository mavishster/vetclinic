<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Остатки</h1>
      <div class="text-subtitle1">На сумму: <b>{{ money(totals.cost) }}</b></div>
    </div>
    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Товар или артикул" class="col-12 col-md-4"
        @update:model-value="load"><template #prepend><q-icon name="search" /></template></q-input>
      <q-select v-model="warehouse" :options="warehouses" option-value="id" option-label="name" emit-value map-options dense
        outlined clearable label="Склад" class="col-6 col-md-3" @update:model-value="load" />
      <q-checkbox v-model="expiring" label="Срок годности истекает в ближайшие 90 дней" dense @update:model-value="load" />
    </div>
    <q-table :rows="rows" :columns="columns" row-key="key" flat bordered :loading="loading" :pagination="{ rowsPerPage: 100 }"
      no-data-label="Остатков нет" rows-per-page-label="Строк на странице">
      <template #body-cell-expiry="props">
        <q-td :props="props" :class="expiryClass(props.row.expiry_date)">{{ fmt(props.row.expiry_date) }}</q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
// Остатки по товарам, складам и партиям. Остаток — в единице учёта (таб., мл, шт.).
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { money } from '@/modules/catalog/money'

const rows = ref([])
const totals = ref({ cost: 0 })
const loading = ref(false)
const search = ref('')
const warehouse = ref(null)
const expiring = ref(false)
const warehouses = ref([])
const fmt = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')
const qty = (value) => Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 3 })
function expiryClass(iso) {
  if (!iso) return ''
  const days = (new Date(iso) - new Date()) / 86400000
  return days < 0 ? 'text-negative text-weight-bold' : days < 90 ? 'text-warning text-weight-medium' : ''
}
const columns = [
  { name: 'item', label: 'Товар', field: 'item_name', align: 'left', sortable: true, classes: 'text-weight-medium' },
  { name: 'warehouse', label: 'Склад', field: 'warehouse_name', align: 'left', sortable: true },
  { name: 'series', label: 'Серия', field: 'series', align: 'left' },
  { name: 'expiry', label: 'Годен до', field: 'expiry_date', align: 'left', sortable: true },
  { name: 'qty', label: 'Остаток', field: (r) => `${qty(r.qty)} ${r.unit}`, align: 'right' },
  { name: 'cost', label: 'По закупке', field: (r) => money(r.cost), align: 'right' },
]

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (search.value) params.set('search', search.value)
  if (warehouse.value) params.set('warehouse', warehouse.value)
  if (expiring.value) params.set('expiring_days', '90')
  const { data } = await apiGet(`inventory/stock/balances/?${params}`)
  rows.value = (data?.rows ?? []).map((r, i) => ({ ...r, key: `${r.item}-${r.warehouse}-${r.batch}-${i}` }))
  totals.value = data?.totals ?? { cost: 0 }
  loading.value = false
}

onMounted(async () => {
  warehouses.value = (await apiGet('inventory/warehouses/?active=true')).data ?? []
  load()
})
</script>
