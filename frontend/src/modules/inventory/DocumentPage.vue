<template>
  <q-page padding>
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" to="/inventory/documents" />
        <q-icon :name="DOC_KINDS[form.kind].icon" :color="DOC_KINDS[form.kind].color" size="28px" />
        <h1 class="text-h5 q-my-none">{{ DOC_KINDS[form.kind].label }}{{ form.number ? ` № ${form.number}` : '' }}</h1>
        <q-badge v-if="form.id" :color="executed ? 'positive' : 'grey-6'" :label="executed ? 'выполнен' : 'черновик'" />
        <q-space />
        <template v-if="!executed && canEdit">
          <q-btn v-if="form.id && can('inventory.delete_stockdocument')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
          <q-btn outline color="primary" icon="save" label="Сохранить черновик" :loading="busy === 'save'" @click="save()" />
          <q-btn color="positive" unelevated icon="task_alt" label="Выполнить" :loading="busy === 'execute'" @click="execute" />
        </template>
        <q-btn v-if="form.id && form.lines.length" flat icon="qr_code_2" label="Этикетки" @click="printLabels">
          <q-tooltip>Этикетки со штрихкодами на каждую строку — по количеству</q-tooltip>
        </q-btn>
        <q-btn v-if="executed && canEdit" outline color="warning" icon="undo" label="Откатить" :loading="busy === 'rollback'" @click="rollback" />
      </div>

      <div class="row q-col-gutter-sm q-mb-md">
        <q-input v-model="dateText" type="datetime-local" label="Дата" stack-label outlined dense class="col-12 col-sm-3" :readonly="executed" />
        <q-select v-model="form.warehouse" :options="warehouses" option-value="id" option-label="name" emit-value map-options
          outlined dense :label="form.kind === 'transfer' ? 'Со склада' : 'Склад'" class="col-12 col-sm-3" :readonly="executed" />
        <q-select v-if="form.kind === 'transfer'" v-model="form.target_warehouse" :options="warehouses" option-value="id"
          option-label="name" emit-value map-options outlined dense label="На склад" class="col-12 col-sm-3" :readonly="executed" />
        <template v-if="form.kind === 'receipt' || form.kind === 'return'">
          <q-select v-model="form.counterparty" :options="counterparties" option-value="id" option-label="name" emit-value
            map-options outlined dense clearable use-input input-debounce="0" new-value-mode="add-unique" label="Поставщик"
            class="col-12 col-sm-3" :readonly="executed" @new-value="addCounterparty" />
          <q-input v-if="form.kind === 'receipt'" v-model="form.supplier_number" label="№ накладной поставщика" outlined dense class="col-6 col-sm-2" :readonly="executed" />
          <q-input v-if="form.kind === 'receipt'" v-model="form.supplier_date" type="date" label="от" stack-label outlined dense class="col-6 col-sm-2" :readonly="executed" />
        </template>
        <q-input v-if="form.kind === 'write_off'" v-model="form.reason" label="Причина списания" outlined dense class="col-12 col-sm-4"
          :readonly="executed" />
        <q-input v-model="form.comment" label="Комментарий" outlined dense class="col-12" :readonly="executed" />
      </div>

      <div v-if="form.kind === 'inventory' && !executed" class="row q-col-gutter-sm items-center q-mb-sm">
        <q-select v-model="fillGroup" :options="groups" option-value="id" option-label="name" emit-value map-options outlined dense
          clearable label="Только группа" class="col-12 col-sm-4" />
        <div class="col-auto">
          <q-btn color="warning" unelevated icon="playlist_add_check" label="Заполнить остатками склада" :loading="busy === 'fill'" @click="fill" />
        </div>
        <div class="col text-caption text-grey-7">
          В строки встанут учётные остатки по партиям, «насчитано» сразу равно учёту — исправьте только расхождения.
          Найденный товар, которого нет в учёте, добавьте сканером или поиском и укажите закупочную цену.
        </div>
      </div>

      <div v-if="!executed" class="row q-col-gutter-sm items-center q-mb-sm">
        <q-input ref="scanner" v-model="barcode" outlined dense class="col-12 col-sm-4" placeholder="Сканер: штрихкод + Enter"
          @keydown.enter.prevent="scan"><template #prepend><q-icon name="qr_code_scanner" /></template></q-input>
        <q-select v-model="picked" :options="found" option-value="item_unit" option-label="label" emit-value use-input input-debounce="300"
          outlined dense class="col-12 col-sm-8" label="Добавить товар: название или артикул" @filter="searchItems"
          @update:model-value="addFromSearch" />
      </div>

      <q-markup-table flat bordered dense wrap-cells>
        <thead>
          <tr>
            <th class="text-left">Товар</th><th class="text-left">Единица</th>
            <th v-if="form.kind === 'inventory'">По учёту</th>
            <th>{{ form.kind === 'inventory' ? 'Насчитано' : 'Кол-во' }}</th>
            <th v-if="form.kind === 'inventory'">Разница</th>
            <template v-if="form.kind === 'receipt'"><th>Цена за ед.</th><th>Сумма</th><th>Серия</th><th>Годен до</th></template>
            <template v-else-if="form.kind === 'inventory'"><th class="text-left">Партия</th><th>Цена за ед.</th></template>
            <th v-else class="text-left">Партия</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="(line, i) in form.lines" :key="i">
            <td>{{ line.item_name }}<div class="text-caption text-grey-7">= {{ base(line) }} {{ line.base_unit }}</div></td>
            <td style="min-width: 110px">
              <q-select v-model="line.item_unit" :options="line.units" option-value="item_unit" option-label="unit_name" emit-value
                map-options dense borderless :readonly="executed" />
            </td>
            <td v-if="form.kind === 'inventory'" class="text-right text-grey-8">
              {{ line.qty_expected === null || line.qty_expected === undefined ? '—' : `${Number(line.qty_expected)} ${line.base_unit}` }}
            </td>
            <td style="width: 100px"><q-input v-model="line.quantity" type="number" step="0.001" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
            <td v-if="form.kind === 'inventory'" class="text-right text-weight-medium" :class="diffClass(line)">{{ diffText(line) }}</td>
            <template v-if="form.kind === 'receipt'">
              <td style="width: 120px"><q-input v-model="line.price" type="number" step="0.01" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
              <td class="text-right">{{ money((Number(line.price) || 0) * (Number(line.quantity) || 0)) }}</td>
              <td style="width: 120px"><q-input v-model="line.series" dense borderless :readonly="executed" /></td>
              <td style="width: 150px"><q-input v-model="line.expiry_date" type="date" dense borderless :readonly="executed" /></td>
            </template>
            <template v-else-if="form.kind === 'inventory'">
              <td>{{ line.batch_label || (line.batch ? 'партия' : 'новая партия') }}</td>
              <td style="width: 110px">
                <q-input v-if="!line.batch" v-model="line.price" type="number" step="0.01" min="0" dense borderless input-class="text-right"
                  :readonly="executed" placeholder="как прошлая" />
              </td>
            </template>
            <td v-else style="min-width: 200px">
              <q-select v-model="line.batch" :options="line.batches" option-value="batch" option-label="label" emit-value map-options
                dense borderless clearable :readonly="executed" :placeholder="executed ? '' : 'по сроку годности'"
                @focus="loadBatches(line)" />
            </td>
            <td class="text-right"><q-btn v-if="!executed" flat round dense size="sm" icon="close" @click="form.lines.splice(i, 1)" /></td>
          </tr>
          <tr v-if="!form.lines.length"><td colspan="8" class="text-grey-7">Отсканируйте штрихкод или найдите товар по названию</td></tr>
        </tbody>
      </q-markup-table>
      <div class="row q-mt-sm">
        <div class="text-caption text-grey-7 col">
          <template v-if="form.kind === 'receipt'">Каждая строка прихода — новая партия с серией, сроком и закупочной ценой.</template>
          <template v-else-if="form.kind === 'inventory'">При выполнении недостача спишется, излишек оприходуется. Разница считается от остатка на момент выполнения — продажи во время пересчёта учтутся.</template>
          <template v-else>Партия пустая — товар спишется из партий с ближайшим сроком годности.</template>
        </div>
        <div v-if="form.kind === 'receipt'" class="text-subtitle1">Итого: <b>{{ money(total) }}</b></div>
      </div>
      <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
    </template>
  </q-page>
</template>

<script setup>
// Складской документ: приход, расход, перемещение. Строки — сканером или поиском.
// Количество — в любой единице товара, остаток ведётся в единице учёта.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, existingByName, fieldErrors, openPostedFile } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import { DOC_KINDS } from './routes'

const props = defineProps({ id: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const canEdit = can('inventory.change_stockdocument') || can('inventory.add_stockdocument')
const loading = ref(true)
const busy = ref('')
const error = ref('')
const form = ref({ kind: 'receipt', lines: [] })
const warehouses = ref([])
const counterparties = ref([])
const barcode = ref('')
const groups = ref([])
const fillGroup = ref(null)

// Разница инвентаризации — в единицах учёта: насчитано − по учёту.
function diffOf(line) {
  if (line.qty_expected === null || line.qty_expected === undefined) return base(line)
  return Number((base(line) - Number(line.qty_expected)).toFixed(3))
}
const diffText = (line) => { const d = diffOf(line); return d === 0 ? '0' : `${d > 0 ? '+' : ''}${d} ${line.base_unit}` }
const diffClass = (line) => { const d = diffOf(line); return d < 0 ? 'text-negative' : d > 0 ? 'text-positive' : 'text-grey-6' }

async function fill() {
  busy.value = 'fill'
  if (!(await save(true, false))) return (busy.value = '')
  const { ok, data } = await apiPost(`inventory/documents/${form.value.id}/fill/`, { group: fillGroup.value })
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось заполнить')
  applyDocument(data)
  if (props.id === 'new') router.replace(`/inventory/documents/${data.id}`)
}
const found = ref([])
const picked = ref(null)
const executed = computed(() => form.value.status === 'executed')
const total = computed(() => form.value.lines.reduce((sum, l) => sum + (Number(l.price) || 0) * (Number(l.quantity) || 0), 0))
const pad = (n) => String(n).padStart(2, '0')
const dateText = computed({
  get: () => {
    const d = new Date(form.value.date)
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  },
  set: (value) => (form.value.date = new Date(value).toISOString()),
})
const unitOf = (line) => line.units.find((u) => u.item_unit === line.item_unit)
const base = (line) => Number(((Number(line.quantity) || 0) * Number(unitOf(line)?.ratio || 1)).toFixed(3))

// Все единицы товара — чтобы в строке можно было сменить упаковку на штуки и обратно.
async function unitsOf(itemId, name) {
  const { data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(name)}`)
  return (data ?? []).filter((u) => u.item === itemId)
}

async function addLine(unit) {
  const existing = form.value.lines.find((l) => l.item_unit === unit.item_unit)
  if (existing) {
    existing.quantity = String((Number(existing.quantity) || 0) + 1)
    return
  }
  const units = await unitsOf(unit.item, unit.item_name)
  form.value.lines.push({
    item: unit.item, item_name: unit.item_name, base_unit: unit.base_unit, item_unit: unit.item_unit,
    units: units.length ? units : [unit], quantity: '1', price: null, series: '', expiry_date: null, batch: null, batches: [],
  })
}

async function scan() {
  const code = barcode.value.trim()
  barcode.value = ''
  if (!code) return
  const { data } = await apiGet(`inventory/stock/lookup/?barcode=${encodeURIComponent(code)}`)
  if (!data?.length) return $q.notify({ type: 'warning', message: `Товар со штрихкодом ${code} не найден` })
  addLine(data[0])
}

async function searchItems(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (found.value = data.map((u) => ({ ...u, label: `${u.item_name} — ${u.unit_name} (на складе ${Number(u.stock)} ${u.base_unit})` }))))
}

function addFromSearch(id) {
  const unit = found.value.find((u) => u.item_unit === id)
  if (unit) addLine(unit)
  picked.value = null
}

async function loadBatches(line) {
  const params = new URLSearchParams({ item: line.item })
  if (form.value.warehouse) params.set('warehouse', form.value.warehouse)
  const { data } = await apiGet(`inventory/stock/batches/?${params}`)
  line.batches = (data ?? []).map((b) => ({ ...b, label: `${b.label} · остаток ${Number(b.qty)}` }))
}

async function addCounterparty(name, done) {
  const existing = existingByName(counterparties.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('core/counterparties/', { name })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить' })
  counterparties.value = [...counterparties.value, data]
  done(data.id, 'add-unique')
}

function body() {
  const { lines, ...head } = form.value
  return {
    ...head,
    lines: lines.map((l) => ({
      item_unit: l.item_unit, quantity: l.quantity, price: l.price === '' ? null : l.price, series: l.series,
      expiry_date: l.expiry_date || null, batch: l.batch || null, qty_expected: l.qty_expected ?? null,
    })),
  }
}

// navigate=false — не менять адрес страницы (при «Выполнить» новый документ сначала
// сохраняется, а смена адреса пересоздала бы экран и потеряла сообщение об ошибке).
async function save(silent = false, navigate = true) {
  error.value = ''
  busy.value = busy.value || 'save'
  const { ok, data } = form.value.id
    ? await apiPatch(`inventory/documents/${form.value.id}/`, body())
    : await apiPost('inventory/documents/', body())
  if (busy.value === 'save') busy.value = ''
  if (!ok) {
    error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить'
    return false
  }
  if (!form.value.id) {
    form.value.id = data.id
    if (navigate) router.replace(`/inventory/documents/${data.id}`)
  }
  form.value.number = data.number
  if (!silent) $q.notify({ type: 'positive', message: 'Черновик сохранён' })
  return true
}

async function execute() {
  busy.value = 'execute'
  if (!(await save(true, false))) return (busy.value = '')
  const { ok, data } = await apiPost(`inventory/documents/${form.value.id}/execute/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось выполнить')
  $q.notify({ type: 'positive', message: 'Документ выполнен — остатки обновлены' })
  if (props.id === 'new') return router.replace(`/inventory/documents/${data.id}`)
  applyDocument(data)
}

async function rollback() {
  busy.value = 'rollback'
  const { ok, data } = await apiPost(`inventory/documents/${form.value.id}/rollback/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось откатить')
  applyDocument(data)
  $q.notify({ type: 'positive', message: 'Документ откачен — снова черновик' })
}

async function printLabels() {
  if (!executed.value && !(await save(true, false))) return
  const { ok, data } = await openPostedFile('inventory/labels/', { document: form.value.id })
  if (!ok) error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось напечатать этикетки'
}

function remove() {
  $q.dialog({
    title: 'Удалить черновик?', cancel: { label: 'Отмена', flat: true }, ok: { label: 'Удалить', color: 'negative', unelevated: true },
  }).onOk(async () => {
    const { ok } = await apiDelete(`inventory/documents/${form.value.id}/`)
    if (ok) router.push('/inventory/documents')
  })
}

function applyDocument(data) {
  form.value = {
    ...data,
    lines: data.lines.map((l) => ({
      ...l, units: [{ item_unit: l.item_unit, unit_name: l.unit_name, ratio: (Number(l.qty_base) / Number(l.quantity)).toString() }],
      batches: l.batch ? [{ batch: l.batch, label: l.batch_label }] : [],
    })),
  }
}

onMounted(async () => {
  const [w, c, g] = await Promise.all([
    apiGet('inventory/warehouses/?active=true'), apiGet('core/counterparties/?active=true&use=receipt'),
    apiGet('catalog/groups/?active=true&kind=goods'),
  ])
  warehouses.value = w.data ?? []
  counterparties.value = c.data ?? []
  groups.value = g.data ?? []
  if (props.id === 'new') {
    form.value = { kind: route.query.kind || 'receipt', date: new Date().toISOString(), warehouse: warehouses.value[0]?.id ?? null,
      target_warehouse: null, counterparty: null, supplier_number: '', supplier_date: null, reason: '', comment: '', lines: [] }
  } else {
    const { ok, data } = await apiGet(`inventory/documents/${props.id}/`)
    if (ok) applyDocument(data)
    // единицы строк черновика — полный список, чтобы можно было сменить
    if (ok && !executed.value) for (const line of form.value.lines) {
      const units = await unitsOf(line.item, line.item_name)
      if (units.length) line.units = units
    }
  }
  loading.value = false
})
</script>
