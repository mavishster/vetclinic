<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Отделения</h1>
      <q-btn v-if="canIssue" color="primary" unelevated icon="move_down" label="Выдать" @click="open('issue')" />
      <q-btn v-if="canCount" color="primary" outline icon="fact_check" label="Внести остатки" @click="open('count')" />
      <q-btn v-if="canIssue" flat color="primary" icon="assignment_return" label="Вернуть на склад" @click="open('return')" />
    </div>

    <div class="row q-col-gutter-sm q-mb-sm items-center">
      <q-select v-model="department" :options="departments" option-value="id" option-label="name" emit-value map-options dense outlined
        clearable label="Все отделения" class="col-12 col-sm-4" @update:model-value="reload" />
      <div v-if="status" class="col text-caption text-grey-8">
        Ответственный: {{ status.responsible || 'не назначен' }} ·
        последняя выдача: <b>{{ status.last_issue ? `${when(status.last_issue.date)} — ${status.last_issue.created_by}` : 'не было' }}</b> ·
        последний пересчёт: <b>{{ status.last_count ? `${when(status.last_count.date)} — ${status.last_count.created_by}` : 'не было' }}</b>
      </div>
    </div>

    <!-- Предупреждения: остатки не внесены, давно не было выдачи, ниже нормы -->
    <q-banner v-for="a in shownAlerts" :key="a.department + a.kind" dense rounded class="q-mb-xs"
      :class="a.level === 'negative' ? 'row-highlight-negative' : 'row-highlight-warning'">
      <template #avatar><q-icon :name="a.level === 'negative' ? 'error' : 'warning'" :color="a.level === 'negative' ? 'negative' : 'warning'" /></template>
      <b>{{ a.department_name }}:</b> {{ a.message }}
    </q-banner>

    <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary" class="q-mt-sm" @update:model-value="reload">
      <q-tab name="stock" label="Остатки" icon="inventory_2" />
      <q-tab name="journal" label="Журнал по датам" icon="history" />
      <q-tab name="summary" label="Расход за период" icon="insights" />
      <q-tab name="norms" label="Нормы" icon="rule" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <!-- Остатки -->
    <template v-if="tab === 'stock'">
      <div class="row q-col-gutter-sm q-mb-sm items-center">
        <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Материал" class="col-12 col-sm-4" @update:model-value="reload">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <div v-if="showCost && stock.cost !== null" class="col text-right text-subtitle1">На сумму: <b>{{ money(stock.cost) }}</b></div>
      </div>
      <q-table :rows="stock.rows" :columns="stockColumns" row-key="key" flat bordered dense :loading="loading" :pagination="{ rowsPerPage: 100 }"
        no-data-label="В отделениях ничего не числится" rows-per-page-label="Строк на странице">
        <template #body-cell-qty="props">
          <q-td :props="props" :class="props.row.below_norm ? 'text-negative text-weight-bold' : 'text-weight-medium'">
            {{ props.row.qty_text }}<q-badge v-if="props.row.below_norm" color="negative" label="ниже нормы" class="q-ml-sm" />
          </q-td>
        </template>
        <template #body-cell-expiry="props">
          <q-td :props="props" :class="expiryClass(props.row.expiry_date)">{{ day(props.row.expiry_date) }}</q-td>
        </template>
      </q-table>
      <template v-if="!department && stock.totals.length">
        <div class="text-subtitle1 q-mt-lg q-mb-sm">Всего во всех отделениях</div>
        <q-markup-table flat bordered dense>
          <thead><tr><th class="text-left">Материал</th><th class="text-right">Общее количество</th><th class="text-right">Отделений</th>
            <th v-if="showCost" class="text-right">Сумма</th></tr></thead>
          <tbody>
            <tr v-for="t in stock.totals" :key="t.item">
              <td>{{ t.item_name }}</td><td class="text-right text-weight-medium">{{ t.qty_text }}</td>
              <td class="text-right">{{ t.departments }}</td><td v-if="showCost" class="text-right">{{ money(t.cost) }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </template>
    </template>

    <!-- Журнал и сводка за период -->
    <template v-if="tab === 'journal' || tab === 'summary'">
      <div class="row q-col-gutter-sm items-center q-mb-md">
        <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-sm-2" @update:model-value="reload" />
        <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-sm-2" @update:model-value="reload" />
        <q-space />
        <q-btn outline color="primary" icon="download" label="Excel" :href="excelUrl" />
      </div>
      <q-table v-if="tab === 'journal'" :rows="journal" :columns="journalColumns" row-key="key" flat bordered dense :loading="loading"
        :pagination="{ rowsPerPage: 100 }" no-data-label="За период операций не было" rows-per-page-label="Строк на странице">
        <template #body-cell-operation="props">
          <q-td :props="props"><q-chip dense square :color="OPERATION_COLORS[props.row.operation]" text-color="white" :label="props.row.operation_label" /></q-td>
        </template>
        <template #body-cell-number="props">
          <q-td :props="props"><router-link :to="`/inventory/documents/${props.row.document}`" class="text-primary">{{ props.row.number }}</router-link></q-td>
        </template>
      </q-table>
      <template v-else>
        <div class="text-caption text-grey-7 q-mb-sm">
          Расход отделения — это недостача при внесении остатков: было (остаток + выдано) минус осталось.
          «Остатки не внесены» — после последней выдачи пересчёта ещё не было, расход по ней пока неизвестен.
        </div>
        <q-table :rows="summary" :columns="summaryColumns" row-key="key" flat bordered dense :loading="loading" :pagination="{ rowsPerPage: 100 }"
          no-data-label="За период движений не было" rows-per-page-label="Строк на странице">
          <template #body-cell-department="props">
            <q-td :props="props">{{ props.row.department_name }}
              <q-badge v-if="props.row.not_counted" color="warning" label="остатки не внесены" class="q-ml-xs" />
            </q-td>
          </template>
        </q-table>
      </template>
    </template>

    <!-- Нормы: задаёт главный администратор -->
    <template v-if="tab === 'norms'">
      <div class="text-caption text-grey-7 q-mb-sm">
        Норма — сколько материала должно быть в отделении. Ниже нормы — предупреждение и кнопка «Пополнить до нормы» при выдаче.
        <template v-if="!canNorms">Нормы задаёт сотрудник с особым правом «Отделения: нормы, контроль…».</template>
      </div>
      <div v-if="canNorms" class="row q-col-gutter-sm items-center q-mb-md">
        <q-select v-model="normForm.department" :options="departments" option-value="id" option-label="name" emit-value map-options dense
          outlined label="Отделение" class="col-12 col-sm-3" />
        <q-select v-model="normForm.item" :options="normOptions" option-label="label" use-input input-debounce="300" dense outlined clearable
          label="Материал" class="col-12 col-sm-4" @filter="searchNorm" @update:model-value="pickNormItem" />
        <q-select v-model="normForm.item_unit" :options="normUnits" option-value="item_unit" option-label="unit_name" emit-value map-options
          dense outlined label="Единица" class="col-6 col-sm-2" />
        <q-input v-model="normForm.quantity" type="number" step="any" min="0" dense outlined label="Норма" class="col-6 col-sm-1" />
        <div class="col-12 col-sm-2"><q-btn color="primary" unelevated icon="save" label="Задать" :disable="!normReady" @click="saveNorm" /></div>
      </div>
      <q-markup-table flat bordered dense>
        <thead><tr><th class="text-left">Отделение</th><th class="text-left">Материал</th><th class="text-right">Норма</th><th v-if="canNorms"></th></tr></thead>
        <tbody>
          <tr v-for="n in norms" :key="n.id">
            <td>{{ n.department_name }}</td><td>{{ n.item_name }}</td><td class="text-right">{{ n.norm_text }}</td>
            <td v-if="canNorms" class="text-right"><q-btn flat dense round icon="delete" color="negative" @click="removeNorm(n)"><q-tooltip>Убрать норму</q-tooltip></q-btn></td>
          </tr>
          <tr v-if="!norms.length"><td colspan="4" class="text-grey-7">Норм нет</td></tr>
        </tbody>
      </q-markup-table>
    </template>

    <DepartmentOperationDialog v-model="dialog" :mode="mode" :department="department" :departments="departments" @done="reload" />
  </q-page>
</template>

<script setup>
// Склады отделений (ADR-024): остатки (с общим количеством по всем отделениям), выдача,
// внесение остатков, возврат, журнал по датам с тем, кто выдал и кто внёс остатки,
// расход за период, нормы. Остатки — «5,25 упак. / 5 упак. 2 таб.».
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import DepartmentOperationDialog from './DepartmentOperationDialog.vue'

const $q = useQuasar()
const route = useRoute()
const canIssue = can('inventory.add_stockdocument')
const canCount = can('inventory.count_department')
const canNorms = can('inventory.manage_department')
const showCost = can('catalog.view_cost')
const OPERATION_COLORS = { issue: 'primary', return: 'blue-grey', consumed: 'negative', surplus: 'positive', writeoff: 'deep-orange' }

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const day = (v) => (v ? new Date(v).toLocaleDateString('ru-RU') : '—')
const when = (v) => new Date(v).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
const signed = (row, field) => (Number(row[field]) > 0 ? `+${row[`${field}_text`]}` : row[`${field}_text`])
function expiryClass(v) {
  if (!v) return ''
  const days = (new Date(v) - new Date()) / 86400000
  return days < 0 ? 'text-negative text-weight-bold' : days < 90 ? 'text-warning text-weight-medium' : ''
}

const departments = ref([])
const department = ref(route.query.department || null)
const tab = ref(route.query.tab || 'stock')
const search = ref('')
const status = ref(null)
const alerts = ref([])
const stock = ref({ rows: [], totals: [], cost: null })
const journal = ref([])
const summary = ref([])
const norms = ref([])
const loading = ref(false)
const dialog = ref(false)
const mode = ref('issue')
const today = new Date()
const from = ref(iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 30)))
const to = ref(iso(today))

const shownAlerts = computed(() => alerts.value.filter((a) => !department.value || a.department === department.value))
const period = computed(() => {
  const params = new URLSearchParams({ from: from.value, to: to.value })
  if (department.value) params.set('department', department.value)
  return params
})
const excelUrl = computed(() => `/api/inventory/reports/${tab.value === 'journal' ? 'department-journal' : 'departments'}/?${period.value}&export=xlsx`)

const stockColumns = computed(() => [
  ...(department.value ? [] : [{ name: 'department', label: 'Отделение', field: 'department_name', align: 'left', sortable: true }]),
  { name: 'item', label: 'Материал', field: 'item_name', align: 'left', sortable: true, classes: 'text-weight-medium' },
  { name: 'qty', label: 'Остаток', field: 'qty_text', align: 'right' },
  { name: 'norm', label: 'Норма', field: (r) => r.norm_text || '', align: 'right' },
  { name: 'expiry', label: 'Ближайший срок', field: 'expiry_date', align: 'left' },
  ...(showCost ? [{ name: 'cost', label: 'Сумма', field: (r) => money(r.cost), align: 'right' }] : []),
])
const journalColumns = [
  { name: 'date', label: 'Дата', field: (r) => when(r.date), align: 'left' },
  { name: 'operation', label: 'Операция', field: 'operation_label', align: 'left' },
  { name: 'number', label: 'Документ', field: 'number', align: 'left' },
  { name: 'department', label: 'Отделение', field: 'department_name', align: 'left' },
  { name: 'item', label: 'Материал', field: 'item_name', align: 'left', classes: 'text-weight-medium' },
  { name: 'qty', label: 'Количество', field: (r) => signed(r, 'qty'), align: 'right' },
  { name: 'balance', label: 'Остаток после', field: 'balance_text', align: 'right' },
  { name: 'created_by', label: 'Ввёл', field: 'created_by', align: 'left' },
  { name: 'executed_by', label: 'Провёл', field: 'executed_by', align: 'left' },
]
const summaryColumns = [
  { name: 'department', label: 'Отделение', field: 'department_name', align: 'left' },
  { name: 'item', label: 'Материал', field: 'item_name', align: 'left', classes: 'text-weight-medium' },
  { name: 'opening', label: 'На начало', field: 'opening_text', align: 'right' },
  { name: 'issued', label: 'Выдано', field: 'issued_text', align: 'right' },
  { name: 'returned', label: 'Возвращено', field: (r) => (Number(r.returned) ? r.returned_text : ''), align: 'right' },
  { name: 'consumed', label: 'Израсходовано', field: 'consumed_text', align: 'right', classes: 'text-weight-medium' },
  { name: 'surplus', label: 'Излишек', field: (r) => (Number(r.surplus) ? r.surplus_text : ''), align: 'right' },
  { name: 'closing', label: 'На конец', field: 'closing_text', align: 'right' },
  ...(showCost ? [{ name: 'cost', label: 'Сумма расхода', field: (r) => money(r.cost), align: 'right' }] : []),
]

function open(value) {
  mode.value = value
  dialog.value = true
}

async function reload() {
  loading.value = true
  status.value = department.value ? (await apiGet(`inventory/department-stock/status/?department=${department.value}`)).data : null
  apiGet('inventory/department-stock/alerts/').then(({ data }) => (alerts.value = data ?? []))
  if (tab.value === 'stock') {
    const params = new URLSearchParams({ search: search.value || '' })
    if (department.value) params.set('department', department.value)
    const { data } = await apiGet(`inventory/department-stock/balances/?${params}`)
    stock.value = data ?? { rows: [], totals: [], cost: null }
    stock.value.rows = stock.value.rows.map((r) => ({ ...r, key: `${r.department}-${r.item}` }))
  } else if (tab.value === 'journal') {
    journal.value = ((await apiGet(`inventory/reports/department-journal/?${period.value}`)).data ?? []).map((r, i) => ({ ...r, key: i }))
  } else if (tab.value === 'summary') {
    summary.value = ((await apiGet(`inventory/reports/departments/?${period.value}`)).data ?? []).map((r) => ({ ...r, key: `${r.department}-${r.item}` }))
  } else {
    norms.value = (await apiGet(`inventory/department-stock/norms/${department.value ? `?department=${department.value}` : ''}`)).data ?? []
  }
  loading.value = false
}

// --- Нормы ---
const normForm = ref({ department: null, item: null, item_unit: null, quantity: '' })
const normOptions = ref([])
const normUnits = ref([])
const normReady = computed(() => normForm.value.department && normForm.value.item_unit && normForm.value.quantity !== '')

async function searchNorm(text, update, abort) {
  if (text.length < 2) return abort()
  const { data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  const items = new Map()
  for (const u of data ?? []) if (!items.has(u.item)) items.set(u.item, { item: u.item, label: u.item_name })
  update(() => (normOptions.value = [...items.values()]))
}

async function pickNormItem(option) {
  normUnits.value = option ? ((await apiGet(`inventory/stock/lookup/?item=${option.item}`)).data ?? []) : []
  normForm.value.item_unit = normUnits.value[0]?.item_unit ?? null
}

async function saveNorm() {
  const { ok, data } = await apiPost('inventory/department-stock/norm/', normForm.value)
  if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось сохранить' })
  normForm.value = { ...normForm.value, item: null, item_unit: null, quantity: '' }
  normUnits.value = []
  $q.notify({ type: 'positive', message: 'Норма сохранена' })
  window.dispatchEvent(new Event('departments-changed'))
  reload()
}

async function removeNorm(norm) {
  const units = (await apiGet(`inventory/stock/lookup/?item=${norm.item}`)).data ?? []
  const base = units.find((u) => Number(u.ratio) === 1) || units[0]
  await apiPost('inventory/department-stock/norm/', { department: norm.department, item_unit: base.item_unit, quantity: 0 })
  reload()
}

onMounted(async () => {
  departments.value = (await apiGet('inventory/department-stock/list/')).data ?? []
  normForm.value.department = department.value || departments.value[0]?.id || null
  reload()
})
</script>
