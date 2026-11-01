<template>
  <q-page padding>
    <h1 class="text-h5 q-mt-none q-mb-md">Выручка по исполнителям</h1>
    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-md-2" @update:model-value="load" />
      <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-md-2" @update:model-value="load" />
      <div class="col text-caption text-grey-7">По строкам выполненных счетов, со скидками. У комбинаций — по строкам состава.</div>
    </div>
    <q-table :rows="rows" :columns="columns" row-key="name" flat bordered :loading="loading" hide-pagination :pagination="{ rowsPerPage: 0 }"
      no-data-label="За период нет выполненных счетов">
      <template #bottom-row>
        <q-tr class="text-weight-bold"><q-td>Итого</q-td><q-td class="text-right">{{ totals.lines }}</q-td>
          <q-td class="text-right">{{ money(totals.amount) }}</q-td>
          <template v-if="showCost"><q-td class="text-right">{{ money(totals.cost) }}</q-td>
            <q-td class="text-right">{{ money(totals.amount - totals.cost) }}</q-td></template></q-tr>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'

const today = new Date()
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const from = ref(iso(new Date(today.getFullYear(), today.getMonth(), 1)))
const to = ref(iso(today))
const rows = ref([])
const loading = ref(false)
// Себестоимость и прибыль — только с особым правом «Видеть себестоимость».
const showCost = can('catalog.view_cost')
const columns = [
  { name: 'name', label: 'Исполнитель', field: 'name', align: 'left', classes: 'text-weight-medium' },
  { name: 'lines', label: 'Позиций', field: 'lines', align: 'right' },
  { name: 'amount', label: 'Выручка', field: (r) => money(r.amount), align: 'right' },
  ...(showCost
    ? [
        { name: 'cost', label: 'Себестоимость', field: (r) => money(r.cost), align: 'right' },
        { name: 'margin', label: 'Валовая прибыль', field: (r) => money(Number(r.amount) - Number(r.cost)), align: 'right' },
      ]
    : []),
]
const totals = computed(() => rows.value.reduce((t, r) => ({
  lines: t.lines + r.lines, amount: t.amount + Number(r.amount), cost: t.cost + Number(r.cost),
}), { lines: 0, amount: 0, cost: 0 }))

async function load() {
  loading.value = true
  rows.value = (await apiGet(`billing/reports/performers/?from=${from.value}&to=${to.value}`)).data ?? []
  loading.value = false
}
onMounted(load)
</script>
