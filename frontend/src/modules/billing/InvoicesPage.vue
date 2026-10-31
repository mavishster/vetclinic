<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Счета</h1>
      <q-btn v-if="can('billing.add_invoice')" outline color="primary" icon="bolt" label="Быстрый счёт" to="/invoices/new?quick=1">
        <q-tooltip>Продажа без карточки клиента — на «Гостя», с оплатой сразу</q-tooltip>
      </q-btn>
      <q-btn v-if="can('billing.add_invoice')" color="primary" unelevated icon="add" label="Новый счёт" to="/invoices/new" />
    </div>
    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Номер или фамилия клиента" class="col-12 col-md-4"
        @update:model-value="reload"><template #prepend><q-icon name="search" /></template></q-input>
      <q-btn-toggle v-model="status" no-caps unelevated toggle-color="primary" @update:model-value="reload"
        :options="[{ label: 'Все', value: '' }, { label: 'Черновики', value: 'draft' }, { label: 'Выполненные', value: 'executed' }]" />
      <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-md-2" @update:model-value="reload" />
      <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-md-2" @update:model-value="reload" />
    </div>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading" flat bordered
      :rows-per-page-options="[25, 50, 100]" no-data-label="Счетов нет" rows-per-page-label="Строк на странице"
      @request="onRequest" @row-click="(e, row) => $router.push(`/invoices/${row.id}`)">
      <template #body-cell-status="props">
        <q-td :props="props"><q-badge :color="PAY[props.row.payment_status].color" :label="PAY[props.row.payment_status].label" /></q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const status = ref('')
const PAY = {
  paid: { label: 'оплачен', color: 'positive' },
  partial: { label: 'частично', color: 'warning' },
  debt: { label: 'долг', color: 'negative' },
  draft: { label: 'черновик', color: 'grey-6' },
}
const from = ref('')
const to = ref('')
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = [
  { name: 'number', label: '№', field: 'number', align: 'left', classes: 'text-weight-medium' },
  { name: 'date', label: 'Дата', field: (i) => new Date(i.date).toLocaleDateString('ru-RU'), align: 'left' },
  { name: 'client', label: 'Клиент', field: 'client_name', align: 'left' },
  { name: 'pet', label: 'Питомец', field: 'pet_name', align: 'left' },
  { name: 'doctor', label: 'Врач', field: 'doctor_name', align: 'left' },
  { name: 'total', label: 'К оплате', field: (i) => money(i.total), align: 'right' },
  { name: 'status', label: 'Статус', field: 'status', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  for (const [key, value] of Object.entries({ search: search.value, status: status.value, from: from.value, to: to.value })) {
    if (value) params.set(key, value)
  }
  const { ok, data } = await apiGet(`billing/invoices/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}
const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
onMounted(reload)
</script>
