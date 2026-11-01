<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Отчёты</h1>
      <q-btn v-if="current.excel" outline color="primary" icon="download" label="Excel" :href="excelUrl" />
    </div>

    <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary" @update:model-value="load">
      <q-tab v-for="t in tabs" :key="t.name" :name="t.name" :label="t.label" :icon="t.icon" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <div v-if="current.period" class="row q-col-gutter-sm items-center q-mb-md">
      <q-btn-toggle v-model="preset" no-caps unelevated dense toggle-color="primary" :options="PRESETS" @update:model-value="applyPreset" />
      <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-sm-2" @update:model-value="custom" />
      <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-sm-2" @update:model-value="custom" />
      <q-btn-toggle v-if="tab === 'top'" v-model="kind" no-caps unelevated dense toggle-color="primary" @update:model-value="load"
        :options="[{ label: 'Всё', value: '' }, { label: 'Услуги', value: 'service' }, { label: 'Товары', value: 'goods' }]" />
      <q-input v-if="tab === 'turnover'" v-model="search" dense outlined clearable debounce="300" placeholder="Товар"
        class="col-12 col-sm-3" @update:model-value="load" />
    </div>

    <!-- Итоги периода -->
    <div v-if="totals.length" class="row q-col-gutter-md q-mb-md">
      <div v-for="t in totals" :key="t.label" class="col-6 col-md-3">
        <q-card flat bordered><q-card-section class="q-py-sm">
          <div class="text-caption text-grey-7">{{ t.label }}</div>
          <div class="text-h6">{{ t.value }}</div>
        </q-card-section></q-card>
      </div>
    </div>

    <q-table :rows="rows" :columns="columns" row-key="key" flat bordered dense :loading="loading" :pagination="{ rowsPerPage: 100 }"
      :no-data-label="current.empty" rows-per-page-label="Строк на странице">
      <template #body-cell-bar="props">
        <q-td :props="props" style="min-width: 120px">
          <q-linear-progress :value="max ? Number(props.row[current.barField]) / max : 0" color="primary" track-color="transparent" rounded size="8px" />
        </q-td>
      </template>
      <template #body-cell-client="props">
        <q-td :props="props"><router-link :to="`/clients/${props.row.client}`" class="text-primary">{{ props.row.name }}</router-link></q-td>
      </template>
    </q-table>
    <div v-if="tab === 'performers'" class="q-mt-md">
      <q-btn flat no-caps color="primary" icon="bar_chart" label="Открыть отчёт «Выручка по исполнителям»" to="/reports/performers" />
    </div>
  </q-page>
</template>

<script setup>
// Отчёты: продажи и деньги по дням, популярные услуги и товары, должники, движение товара.
// Каждый — с выгрузкой в Excel. Себестоимость видна только с особым правом.
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'

const showCost = can('catalog.view_cost')
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const fmtDay = (v) => (v ? new Date(v).toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' }) : '')
const qty = (v) => Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 3 })
const PRESETS = [
  { label: 'Сегодня', value: 'today' }, { label: '7 дней', value: 'week' },
  { label: 'Этот месяц', value: 'month' }, { label: 'Прошлый месяц', value: 'prev' },
]

const ALL_TABS = [
  {
    name: 'sales', label: 'Продажи и деньги', icon: 'trending_up', perm: 'billing.view_invoice', period: true, excel: 'billing/reports/sales/',
    empty: 'За период продаж нет', barField: 'total',
    columns: () => [
      { name: 'day', label: 'День', field: (r) => fmtDay(r.day), align: 'left' },
      { name: 'invoices', label: 'Счетов', field: 'invoices', align: 'right' },
      { name: 'total', label: 'Продано', field: (r) => money(r.total), align: 'right' },
      { name: 'discount', label: 'Скидки', field: (r) => (Number(r.discount) ? money(r.discount) : ''), align: 'right' },
      ...(showCost ? [{ name: 'margin', label: 'Прибыль', field: (r) => money(Number(r.total) - Number(r.cost)), align: 'right' }] : []),
      ...(can('cash.view_payment') ? [
        { name: 'cash', label: 'Наличные', field: (r) => (r.cash_in ? money(r.cash_in) : ''), align: 'right' },
        { name: 'card', label: 'Безнал', field: (r) => (r.card_in ? money(r.card_in) : ''), align: 'right' },
        { name: 'out', label: 'Выдано', field: (r) => (Number(r.out) ? money(r.out) : ''), align: 'right' },
      ] : []),
      { name: 'bar', label: '', field: 'total' },
    ],
  },
  {
    name: 'top', label: 'Популярное', icon: 'star', perm: 'billing.view_invoice', period: true, excel: 'billing/reports/top-items/',
    empty: 'За период продаж нет', barField: 'amount',
    columns: () => [
      { name: 'name', label: 'Услуга / товар', field: 'name', align: 'left', classes: 'text-weight-medium' },
      { name: 'quantity', label: 'Количество', field: (r) => `${qty(r.quantity)} ${r.unit}`, align: 'right' },
      { name: 'invoices', label: 'В счетах', field: 'invoices', align: 'right' },
      { name: 'amount', label: 'Выручка', field: (r) => money(r.amount), align: 'right' },
      ...(showCost ? [{ name: 'margin', label: 'Прибыль', field: (r) => money(Number(r.amount) - Number(r.cost)), align: 'right' }] : []),
      { name: 'bar', label: '', field: 'amount' },
    ],
  },
  {
    name: 'debtors', label: 'Должники', icon: 'money_off', perm: 'billing.view_invoice', period: false, excel: 'billing/reports/debtors/',
    empty: 'Должников нет', barField: 'debt',
    columns: () => [
      { name: 'client', label: 'Клиент', field: 'name', align: 'left' },
      { name: 'phone', label: 'Телефон', field: 'phone', align: 'left' },
      { name: 'debt', label: 'Долг', field: (r) => money(r.debt), align: 'right', classes: 'text-negative text-weight-medium' },
      { name: 'invoices', label: 'Счетов', field: 'invoices', align: 'right' },
      { name: 'since', label: 'Не оплачено с', field: (r) => new Date(r.since).toLocaleDateString('ru-RU'), align: 'left' },
      { name: 'bar', label: '', field: 'debt' },
    ],
  },
  {
    name: 'turnover', label: 'Движение товара', icon: 'swap_vert', perm: 'inventory.view_stockmovement', period: true, excel: 'inventory/reports/turnover/',
    empty: 'Движений товара за период нет', barField: 'outgoing',
    columns: () => [
      { name: 'name', label: 'Товар', field: 'name', align: 'left', classes: 'text-weight-medium' },
      { name: 'opening', label: 'На начало', field: (r) => qty(r.opening), align: 'right' },
      { name: 'incoming', label: 'Пришло', field: (r) => (Number(r.incoming) ? `+${qty(r.incoming)}` : ''), align: 'right', classes: 'text-positive' },
      { name: 'outgoing', label: 'Ушло', field: (r) => (Number(r.outgoing) ? `−${qty(r.outgoing)}` : ''), align: 'right', classes: 'text-negative' },
      { name: 'closing', label: 'На конец', field: (r) => `${qty(r.closing)} ${r.unit}`, align: 'right', classes: 'text-weight-medium' },
    ],
  },
  { name: 'performers', label: 'Исполнители', icon: 'badge', perm: 'billing.view_invoice', period: false, empty: '', columns: () => [] },
]
const tabs = ALL_TABS.filter((t) => can(t.perm))
const tab = ref(tabs[0]?.name)
const current = computed(() => tabs.find((t) => t.name === tab.value) || {})
const columns = computed(() => current.value.columns?.() ?? [])

const preset = ref('month')
const from = ref('')
const to = ref('')
const kind = ref('')
const search = ref('')
const rows = ref([])
const loading = ref(false)
const max = computed(() => Math.max(0, ...rows.value.map((r) => Number(r[current.value.barField]) || 0)))

function applyPreset(value) {
  const today = new Date()
  const start = new Date(today)
  let end = today
  if (value === 'week') start.setDate(today.getDate() - 6)
  if (value === 'month') start.setDate(1)
  if (value === 'prev') {
    start.setMonth(today.getMonth() - 1, 1)
    end = new Date(today.getFullYear(), today.getMonth(), 0)
  }
  from.value = iso(start)
  to.value = iso(end)
  load()
}
function custom() {
  preset.value = null
  load()
}

const query = computed(() => {
  const params = new URLSearchParams({ from: from.value, to: to.value })
  if (tab.value === 'top' && kind.value) params.set('kind', kind.value)
  if (tab.value === 'turnover' && search.value) params.set('search', search.value)
  return params
})
const excelUrl = computed(() => `/api/${current.value.excel}?${query.value}&export=xlsx`)

const totals = computed(() => {
  const sum = (field) => rows.value.reduce((s, r) => s + (Number(r[field]) || 0), 0)
  if (tab.value === 'sales') {
    const list = [{ label: 'Продано', value: money(sum('total')) }, { label: 'Счетов', value: sum('invoices') }]
    if (can('cash.view_payment')) list.push({ label: 'Поступило денег', value: money(sum('cash_in') + sum('card_in')) })
    if (showCost) list.push({ label: 'Валовая прибыль', value: money(sum('total') - sum('cost')) })
    return list
  }
  if (tab.value === 'top') return [{ label: 'Выручка', value: money(sum('amount')) }, { label: 'Позиций', value: rows.value.length }]
  if (tab.value === 'debtors') return [{ label: 'Всего долгов', value: money(sum('debt')) }, { label: 'Должников', value: rows.value.length }]
  return []
})

async function load() {
  if (!current.value.excel) return (rows.value = [])
  loading.value = true
  const { data } = await apiGet(`${current.value.excel}?${query.value}`)
  let list = data ?? []
  if (tab.value === 'sales' && can('cash.view_payment')) {
    // Продажи и деньги — в одной таблице по дням.
    const moneyRows = (await apiGet(`cash/reports/money/?${query.value}`)).data ?? []
    const byDay = new Map(list.map((r) => [r.day, { ...r }]))
    for (const m of moneyRows) byDay.set(m.day, { day: m.day, invoices: 0, total: 0, discount: 0, cost: 0, ...byDay.get(m.day), ...m })
    list = [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day))
  }
  rows.value = list.map((r, i) => ({ ...r, key: r.day || r.item || r.client || i }))
  loading.value = false
}

onMounted(() => applyPreset('month'))
</script>
