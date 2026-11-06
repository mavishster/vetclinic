<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Остатки</h1>
      <div v-if="showCost" class="text-subtitle1">На сумму: <b>{{ money(totals.cost) }}</b></div>
    </div>
    <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary" class="q-mb-md">
      <q-tab name="stock" label="Остатки" />
      <q-tab name="replenish" :label="`Нужно переместить${replenish.length ? ` (${replenish.length})` : ''}`" />
      <q-tab name="low" label="Нужно заказать" />
      <q-tab name="negative" :label="`В минусе${negative.length ? ` (${negative.length})` : ''}`" />
    </q-tabs>
    <LowStock v-if="tab === 'low'" :warehouses="warehouses" />
    <template v-else-if="tab === 'replenish'">
      <div class="row items-center q-mb-sm">
        <div class="text-caption text-grey-7 col">
          На оперативном складе товар в минусе (продали больше, чем переместили) или ниже минимума. Переместите с основного.
        </div>
        <q-btn v-if="can('inventory.add_stockdocument')" color="primary" unelevated icon="move_down" label="Перемещение" to="/inventory/transfer" />
      </div>
      <q-markup-table flat bordered dense>
        <thead><tr><th class="text-left">Товар</th><th class="text-left">Склад</th><th>Сейчас</th><th>Минимум</th><th>Переместить</th><th>Есть на основном</th></tr></thead>
        <tbody>
          <tr v-for="r in replenish" :key="r.item + r.warehouse">
            <td class="text-weight-medium">{{ r.item_name }}</td><td>{{ r.warehouse_name }}</td>
            <td class="text-right" :class="Number(r.qty) < 0 ? 'text-negative' : ''">{{ r.qty_text }}</td>
            <td class="text-right">{{ r.min_qty_text }}</td>
            <td class="text-right text-weight-medium">{{ r.need_text }}</td>
            <td class="text-right" :class="Number(r.available) < Number(r.need) ? 'text-negative' : 'text-positive'">
              {{ r.available_text }}<span v-if="Number(r.available) < Number(r.need)"> — нужно заказать</span>
            </td>
          </tr>
          <tr v-if="!replenish.length"><td colspan="6" class="text-grey-7">Перемещать ничего не нужно</td></tr>
        </tbody>
      </q-markup-table>
    </template>
    <template v-else-if="tab === 'negative'">
      <div class="text-caption text-grey-7 q-mb-sm">Продано больше, чем оприходовано. Минус закроется следующим приходом — оформите его.</div>
      <q-list bordered separator class="rounded-borders">
        <q-item v-for="r in negative" :key="r.item + r.warehouse_name">
          <q-item-section>{{ r.item_name }}<q-item-label caption>{{ r.warehouse_name }}</q-item-label></q-item-section>
          <q-item-section side class="text-negative text-weight-medium">{{ r.qty_text }}</q-item-section>
        </q-item>
        <q-item v-if="!negative.length"><q-item-section class="text-grey-7">Минусов нет</q-item-section></q-item>
      </q-list>
    </template>
    <template v-else>
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
    </template>
  </q-page>
</template>

<script setup>
// Остатки по товарам, складам и партиям: «5,25 упак. / 5 упак. 2 таб.» (упаковки и штуки).
// Склады отделений здесь не показываются — они в «Склад → Отделения» (ADR-024).
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import { useRoute } from 'vue-router'
import LowStock from './LowStock.vue'

const route = useRoute()
const tab = ref(['low', 'negative', 'replenish'].includes(route.query.tab) ? route.query.tab : 'stock')
const replenish = ref([])
const negative = ref([])
const rows = ref([])
const totals = ref({ cost: 0 })
const loading = ref(false)
const search = ref('')
const warehouse = ref(null)
const expiring = ref(route.query.expiring === '1')
const warehouses = ref([])
const fmt = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')
function expiryClass(iso) {
  if (!iso) return ''
  const days = (new Date(iso) - new Date()) / 86400000
  return days < 0 ? 'text-negative text-weight-bold' : days < 90 ? 'text-warning text-weight-medium' : ''
}
const showCost = can('catalog.view_cost') // закупочные цены — только с особым правом
const columns = [
  { name: 'item', label: 'Товар', field: 'item_name', align: 'left', sortable: true, classes: 'text-weight-medium' },
  { name: 'warehouse', label: 'Склад', field: 'warehouse_name', align: 'left', sortable: true },
  { name: 'series', label: 'Серия', field: 'series', align: 'left' },
  { name: 'expiry', label: 'Годен до', field: 'expiry_date', align: 'left', sortable: true },
  { name: 'qty', label: 'Остаток', field: 'qty_text', align: 'right' },
  ...(showCost ? [{ name: 'cost', label: 'По закупке', field: (r) => money(r.cost), align: 'right' }] : []),
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
  apiGet('inventory/stock/negative/').then(({ data }) => (negative.value = data ?? []))
  apiGet('inventory/stock/replenish/').then(({ data }) => (replenish.value = data ?? []))
  warehouses.value = (await apiGet('inventory/warehouses/?active=true')).data ?? []
  load()
})
</script>
