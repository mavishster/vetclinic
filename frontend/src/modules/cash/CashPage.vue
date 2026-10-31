<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Касса</h1>
      <template v-if="can('cash.add_cashoperation')">
        <q-btn outline color="positive" icon="add_card" label="Внесение" @click="openOperation('income')" />
        <q-btn outline color="negative" icon="output" label="Выдача" @click="openOperation('expense')" />
        <q-btn outline color="primary" icon="swap_horiz" label="Перемещение" @click="openOperation('transfer')" />
      </template>
    </div>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="r in registers" :key="r.id" class="col-12 col-sm-6 col-md-4">
        <q-card flat bordered>
          <q-card-section>
            <div class="row items-center">
              <q-icon :name="r.kind === 'cash' ? 'payments' : 'credit_card'" color="primary" size="24px" class="q-mr-sm" />
              <div class="text-subtitle1 col">{{ r.name }}</div>
            </div>
            <div class="text-h5 q-mt-sm">{{ money(r.balance) }}</div>
            <div class="text-caption text-grey-7">
              <template v-if="r.shift_opened_at">Смена с {{ fmt(r.shift_opened_at) }}: +{{ money(r.shift_income) }} / −{{ money(r.shift_expense) }}</template>
              <template v-else>Смена закрыта</template>
            </div>
          </q-card-section>
          <q-card-actions v-if="r.shift_opened_at && can('cash.add_cashoperation')">
            <q-btn flat dense no-caps color="primary" icon="lock" label="Закрыть кассу" @click="closeShift(r)" />
          </q-card-actions>
        </q-card>
      </div>
    </div>

    <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary">
      <q-tab name="payments" label="Оплаты" />
      <q-tab name="operations" label="Кассовые операции" />
      <q-tab name="shifts" label="Закрытия кассы" />
    </q-tabs>
    <q-separator class="q-mb-sm" />

    <q-table v-if="tab === 'payments'" :rows="payments" :columns="paymentColumns" row-key="id" flat bordered dense
      :pagination="{ rowsPerPage: 25 }" no-data-label="Оплат нет" rows-per-page-label="Строк на странице">
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-badge v-if="props.row.status !== 'executed'" color="grey-6" label="возвращена" />
          <q-btn v-else-if="can('cash.add_payment')" flat dense no-caps color="negative" label="Возврат" @click="refund(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-table v-if="tab === 'operations'" :rows="operations" :columns="operationColumns" row-key="id" flat bordered dense
      :pagination="{ rowsPerPage: 25 }" no-data-label="Операций нет" rows-per-page-label="Строк на странице">
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-badge v-if="props.row.status !== 'executed'" color="grey-6" label="отменена" />
          <q-btn v-else-if="can('cash.add_cashoperation')" flat dense no-caps label="Отменить" @click="cancel(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-table v-if="tab === 'shifts'" :rows="shifts" :columns="shiftColumns" row-key="id" flat bordered dense
      :pagination="{ rowsPerPage: 25 }" no-data-label="Закрытий ещё не было" rows-per-page-label="Строк на странице" />

    <q-dialog v-model="operationOpen">
      <q-card style="width: 440px; max-width: 95vw">
        <q-form @submit="saveOperation">
          <q-card-section class="text-h6">{{ KINDS[operation.kind] }}</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <q-select v-model="operation.register" :options="registers" option-value="id" option-label="name" emit-value
              map-options outlined dense :label="operation.kind === 'transfer' ? 'Из кассы' : 'Касса'" />
            <q-select v-if="operation.kind === 'transfer'" v-model="operation.target_register" :options="registers"
              option-value="id" option-label="name" emit-value map-options outlined dense label="В кассу" />
            <q-input v-model="operation.amount" type="number" step="0.01" min="0" outlined dense autofocus label="Сумма" />
            <q-input v-model="operation.purpose" outlined dense label="Назначение"
              :hint="operation.kind === 'expense' ? 'Например: хозяйственные расходы, инкассация' : 'Например: размен'" />
            <div v-if="error" class="text-negative">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn type="submit" color="primary" unelevated label="Провести" :disable="!operation.amount" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
// Касса: остатки по кассам, смена, внесение / выдача / перемещение, оплаты с возвратом, закрытия.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'

const $q = useQuasar()
const KINDS = { income: 'Внесение денег', expense: 'Выдача денег', transfer: 'Перемещение между кассами' }
const registers = ref([])
const payments = ref([])
const operations = ref([])
const shifts = ref([])
const tab = ref('payments')
const operationOpen = ref(false)
const operation = ref({})
const error = ref('')
const fmt = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '')

const paymentColumns = [
  { name: 'date', label: 'Время', field: (r) => fmt(r.date), align: 'left' },
  { name: 'number', label: '№', field: 'number', align: 'left' },
  { name: 'client', label: 'Клиент', field: 'client_name', align: 'left' },
  { name: 'cash', label: 'Наличные', field: (r) => (Number(r.cash_received) ? money(Number(r.cash_received) - Number(r.change_given)) : ''), align: 'right' },
  { name: 'card', label: 'Безнал', field: (r) => (Number(r.card_amount) ? money(r.card_amount) : ''), align: 'right' },
  { name: 'actions', label: '', field: 'id' },
]
const operationColumns = [
  { name: 'date', label: 'Время', field: (r) => fmt(r.date), align: 'left' },
  { name: 'kind', label: 'Операция', field: 'kind_label', align: 'left' },
  { name: 'register', label: 'Касса', field: (r) => (r.target_register_name ? `${r.register_name} → ${r.target_register_name}` : r.register_name), align: 'left' },
  { name: 'amount', label: 'Сумма', field: (r) => money(r.amount), align: 'right' },
  { name: 'purpose', label: 'Назначение', field: (r) => r.client_name || r.purpose, align: 'left' },
  { name: 'actions', label: '', field: 'id' },
]
const shiftColumns = [
  { name: 'register', label: 'Касса', field: 'register', align: 'left' },
  { name: 'opened', label: 'Открыта', field: (r) => fmt(r.opened_at), align: 'left' },
  { name: 'closed', label: 'Закрыта', field: (r) => fmt(r.closed_at) || 'открыта', align: 'left' },
  { name: 'income', label: 'Поступило', field: (r) => money(r.income), align: 'right' },
  { name: 'expense', label: 'Выдано', field: (r) => money(r.expense), align: 'right' },
  { name: 'balance', label: 'Остаток', field: (r) => money(r.closing_balance), align: 'right' },
  { name: 'who', label: 'Закрыл', field: 'closed_by', align: 'left' },
]

async function load() {
  const [s, p, o, sh] = await Promise.all([
    apiGet('cash/cash/summary/'), apiGet('cash/payments/?page_size=50'), apiGet('cash/operations/?page_size=50'), apiGet('cash/cash/shifts/'),
  ])
  registers.value = s.data ?? []
  payments.value = p.data?.results ?? []
  operations.value = o.data?.results ?? []
  shifts.value = sh.data ?? []
}

function openOperation(kind) {
  error.value = ''
  operation.value = { kind, register: registers.value.find((r) => r.kind === 'cash')?.id ?? registers.value[0]?.id, target_register: null, amount: '', purpose: '' }
  operationOpen.value = true
}

async function saveOperation() {
  error.value = ''
  const { ok, data } = await apiPost('cash/operations/', operation.value)
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось провести')
  operationOpen.value = false
  load()
}

function confirmThen(title, message, action) {
  $q.dialog({ title, message, cancel: { label: 'Отмена', flat: true }, ok: { label: 'Да', color: 'primary', unelevated: true } }).onOk(action)
}

function closeShift(register) {
  confirmThen('Закрыть кассу?', `${register.name}: в кассе ${money(register.balance)}. Итоги смены сохранятся; после закрытия вернуть оплаты этой смены будет нельзя.`, async () => {
    const { ok, data } = await apiPost('cash/cash/close-shift/', { register: register.id })
    if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] })
    $q.notify({ type: 'positive', message: `Касса закрыта. Поступило ${money(data.income)}, выдано ${money(data.expense)}` })
    tab.value = 'shifts'
    load()
  })
}

function refund(payment) {
  confirmThen('Вернуть оплату?', `${payment.client_name}: деньги выдаются из кассы, счета снова станут неоплаченными.`, async () => {
    const { ok, data } = await apiPost(`cash/payments/${payment.id}/refund/`)
    if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0], timeout: 8000 })
    load()
  })
}

function cancel(op) {
  confirmThen('Отменить операцию?', `${op.kind_label}: ${money(op.amount)}`, async () => {
    const { ok, data } = await apiPost(`cash/operations/${op.id}/cancel/`)
    if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0], timeout: 8000 })
    load()
  })
}

onMounted(load)
</script>
