<template>
  <q-page padding>
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="40px" color="primary" /></div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" to="/inventory/documents" />
        <q-icon :name="docKind(form.kind).icon" :color="docKind(form.kind).color" size="28px" />
        <h1 class="text-h5 q-my-none">{{ docKind(form.kind).label }}{{ form.number ? ` № ${form.number}` : '' }}</h1>
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
        <q-btn v-if="executed && can('inventory.rollback_stockdocument')" outline color="warning" icon="undo" label="Откатить" :loading="busy === 'rollback'" @click="rollback" />
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
        <q-select v-if="form.kind === 'write_off' && form.department" v-model="form.department" :options="departments" option-value="id" option-label="name"
          emit-value map-options clearable outlined dense label="На отделение" class="col-12 col-sm-3" :readonly="executed"
          hint="Старое списание на отделение. Теперь — «Склад → Отделения»" />
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

      <div v-if="form.kind === 'inventory' && !executed && !form.checklist?.length" class="row q-col-gutter-sm items-center q-mb-sm">
        <q-file v-model="checklistFile" outlined dense accept=".xlsx,.csv" label="Список из файла склада (Excel)" class="col-12 col-sm-4"
          :loading="busy === 'checklist'" @update:model-value="loadChecklist"><template #prepend><q-icon name="checklist" /></template></q-file>
        <div class="col text-caption text-grey-7">
          Старый файл склада (штрихкод, наименование, срок, единица, количество) — откроется списком «что искать на полке»:
          отмечайте найденное, строки попадут в документ, неотмеченное будет подсвечено.
        </div>
      </div>

      <ChecklistPanel v-if="form.kind === 'inventory' && form.checklist?.length" ref="panel" :rows="form.checklist"
        :lines="form.lines" :name="form.checklist_name" :executed="executed" :can-barcodes="can('catalog.change_item')"
        :busy="busy === 'barcodes'" @tick="tickRow" @untick="untickRow" @pick="pickRow" @barcodes="saveBarcodes"
        @clear="clearChecklist" />

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
            <template v-else-if="form.kind === 'inventory'"><th class="text-left">Партия</th><th>Годен до</th><th>Цена за ед.</th></template>
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
            <td style="width: 100px"><q-input v-model="line.quantity" type="number" step="any" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
            <td v-if="form.kind === 'inventory'" class="text-right text-weight-medium" :class="diffClass(line)">{{ diffText(line) }}</td>
            <template v-if="form.kind === 'receipt'">
              <td style="width: 120px"><q-input v-model="line.price" type="number" step="0.01" min="0" dense borderless input-class="text-right" :readonly="executed" /></td>
              <td class="text-right">{{ money((Number(line.price) || 0) * (Number(line.quantity) || 0)) }}</td>
              <td style="width: 120px"><q-input v-model="line.series" dense borderless :readonly="executed" /></td>
              <td style="width: 150px"><q-input v-model="line.expiry_date" type="date" dense borderless :readonly="executed" /></td>
            </template>
            <template v-else-if="form.kind === 'inventory'">
              <td>
                {{ line.batch_label || (line.batch ? 'партия' : 'новая партия') }}
                <q-input v-if="!line.batch" v-model="line.series" dense borderless :readonly="executed" placeholder="серия" />
              </td>
              <td style="width: 150px">
                <q-input v-if="!line.batch" v-model="line.expiry_date" type="date" dense borderless :readonly="executed" />
              </td>
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
          <tr v-if="!form.lines.length"><td colspan="9" class="text-grey-7">Отсканируйте штрихкод или найдите товар по названию</td></tr>
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

    <q-dialog :model-value="!!expiryAsk" @update:model-value="(open) => !open && answerExpiry(null)">
      <q-card v-if="expiryAsk" style="min-width: 340px; max-width: 480px">
        <q-card-section>
          <div class="text-h6">Какой срок у этой пачки?</div>
          <div class="text-grey-7">{{ expiryAsk.item_name }} ({{ expiryAsk.unit_name }}). На обычном штрихкоде срока нет — посмотрите на коробку.</div>
        </q-card-section>
        <q-card-section v-if="expiryAsk.options.length" class="q-pt-none column q-gutter-y-sm">
          <q-btn v-for="(o, i) in expiryAsk.options" :key="i" outline color="primary" no-caps align="left" @click="answerExpiry(o)">
            <div class="column items-start text-left">
              <div class="text-weight-medium">{{ o.expiry ? `годен до ${dateRu(o.expiry)}` : 'без срока' }}{{ o.series ? ` · серия ${o.series}` : '' }}</div>
              <div class="text-caption text-grey-7">{{ o.where }}</div>
            </div>
          </q-btn>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-xs">{{ expiryAsk.options.length ? 'Другой срок' : 'Срок с коробки' }}</div>
          <div class="row q-col-gutter-sm">
            <q-input v-model="expiryAsk.date" type="date" outlined dense class="col-7" label="Годен до" stack-label
              @keydown.enter.prevent="expiryAsk.date && answerExpiry({ expiry: expiryAsk.date, series: expiryAsk.series.trim() })" />
            <q-input v-model="expiryAsk.series" outlined dense class="col-5" label="Серия" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Отмена" @click="answerExpiry(null)" />
          <q-btn flat label="Без срока" @click="answerExpiry({ expiry: null, series: expiryAsk.series.trim() })" />
          <q-btn unelevated color="primary" label="Добавить" :disable="!expiryAsk.date"
            @click="answerExpiry({ expiry: expiryAsk.date, series: expiryAsk.series.trim() })" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog :model-value="!!unknown" @update:model-value="(open) => !open && (unknown = null)">
      <q-card v-if="unknown" style="min-width: 360px; max-width: 520px">
        <q-card-section>
          <div class="text-h6">Штрихкод не найден</div>
          <div class="text-grey-7 ellipsis-2-lines">{{ unknown.code }}</div>
          <div class="q-mt-sm">Если это препарат из справочника в другой коробке — выберите его упаковку, и код запомнится.
            Если препарата нет — заведите его в справочнике.</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-select v-model="unknown.picked" :options="unknown.found" option-value="item_unit" option-label="label" emit-value map-options
            use-input input-debounce="300" outlined dense label="Препарат и упаковка" @filter="searchUnknown" />
          <div v-if="unknown.error" class="text-negative q-mt-sm">{{ unknown.error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Отмена" @click="unknown = null" />
          <q-btn unelevated color="primary" label="Запомнить код" :disable="!unknown.picked" :loading="busy === 'barcode'" @click="rememberCode" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
// Складской документ: приход, расход, перемещение. Строки — сканером или поиском.
// Количество — в любой единице товара, остаток ведётся в единице учёта.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, existingByName, fieldErrors, openPostedFile } from '@/api'
import { can } from '@/session'
import { money } from '@/modules/catalog/money'
import { docKind } from './routes'
import ChecklistPanel from './ChecklistPanel.vue'

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
const checklistFile = ref(null)
const panel = ref(null)

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

// Отсканированное или только что добавленное — первой строкой: не листать вниз.
function toTop(line) {
  const index = form.value.lines.indexOf(line)
  if (index > 0) form.value.lines.unshift(...form.value.lines.splice(index, 1))
}

// --- Сканер: товар по штрихкоду, партия — по сроку и серии (ADR-025) ----------------
// Штрихкод говорит, ЧТО это за товар; какая это пачка — срок и серия. В приходе и
// инвентаризации пачки с разными сроками — разные строки (разные партии). Срок берётся
// из квадратного кода (DataMatrix); на обычном штрихкоде его нет — спрашиваем.
const scanner = ref(null)
const tracksExpiry = computed(() => ['receipt', 'inventory'].includes(form.value.kind))
const expiryOf = (line) => (line.batch ? line.batch_expiry : line.expiry_date) || null
const seriesOf = (line) => (line.batch ? line.batch_series : line.series) || ''
// Та же партия: срок совпадает, серия — если известна с обеих сторон.
const sameBatch = (line, pack) => expiryOf(line) === (pack.expiry || null)
  && (!pack.series || !seriesOf(line) || seriesOf(line) === pack.series)
const ratioOf = (line) => Number(unitOf(line)?.ratio || 1)
const dateRu = (value) => (value ? new Date(value).toLocaleDateString('ru-RU') : '')

// Добавить пачку: та же партия — +1 к её строке (в единице строки), иначе — новая строка.
async function addPack(unit, pack = null, checklistRow = null) {
  const matches = (l) => (pack && tracksExpiry.value
    ? l.item === unit.item && sameBatch(l, pack)
    : l.item_unit === unit.item_unit)
    && (checklistRow === null || l.checklist_row === checklistRow)
  const existing = form.value.lines.find(matches)
  if (existing) {
    const add = Number(unit.ratio || 1) / ratioOf(existing)
    existing.quantity = String(Number(((Number(existing.quantity) || 0) + add).toFixed(3)))
    if (pack?.series && !existing.batch && !existing.series) existing.series = pack.series
    toTop(existing)
    return existing
  }
  const units = await unitsOf(unit.item, unit.item_name)
  const line = {
    item: unit.item, item_name: unit.item_name, base_unit: unit.base_unit, item_unit: unit.item_unit,
    units: units.length ? units : [unit], quantity: '1', price: null, series: pack?.series || '',
    expiry_date: pack?.expiry || null, batch: null, batches: [], qty_expected: null, checklist_row: checklistRow,
  }
  form.value.lines.unshift(line)
  return form.value.lines[0] ?? line
}

// Из поиска по названию: в приходе и инвентаризации — к строке без срока (срок впишут в ней),
// иначе новая строка; в остальных документах — к строке той же единицы.
const addLine = (unit) => addPack(unit, tracksExpiry.value ? { expiry: null, series: '' } : null)

// Сроки, которые уже знаем у этого товара: строки документа и (в инвентаризации) партии склада.
async function knownPacks(unit, fileExpiry = null) {
  const list = []
  const add = (expiry, series, where) => {
    const same = list.find((o) => o.expiry === (expiry || null) && o.series === (series || ''))
    if (same) same.where = `${same.where}, ${where}`
    else list.push({ expiry: expiry || null, series: series || '', where })
  }
  for (const line of form.value.lines) {
    if (line.item === unit.item) add(expiryOf(line), seriesOf(line), `в документе: ${line.quantity} ${unitOf(line)?.unit_name || ''}`)
  }
  if (fileExpiry) add(fileExpiry, '', 'по файлу склада')
  if (form.value.kind === 'inventory' && form.value.warehouse) {
    const params = new URLSearchParams({ item: unit.item, warehouse: form.value.warehouse })
    const { data } = await apiGet(`inventory/stock/batches/?${params}`)
    for (const b of data ?? []) add(b.expiry_date, b.series, `на складе: ${b.qty_text}`)
  }
  return list.sort((x, y) => (x.expiry || '9999').localeCompare(y.expiry || '9999'))
}

// Окно «Какой срок у этой пачки?» — ответ: { expiry, series } или null (отмена).
const expiryAsk = ref(null)
function askExpiry(unit, options) {
  return new Promise((resolve) => {
    expiryAsk.value = { item_name: unit.item_name, unit_name: unit.unit_name, options, date: '', series: '', resolve }
  })
}
function answerExpiry(choice) {
  const ask = expiryAsk.value
  expiryAsk.value = null
  ask?.resolve(choice)
  setTimeout(() => scanner.value?.focus(), 0)
}

async function scan() {
  const code = barcode.value.trim()
  barcode.value = ''
  if (!code) return
  const { data } = await apiGet(`inventory/stock/lookup/?barcode=${encodeURIComponent(code)}`)
  if (!data?.length) return unknownCode(code)
  const unit = data[0]
  const plain = unit.scanned_code || code.replace(/\D/g, '')
  // Список из файла: строка с этим штрихкодом (или с этой позицией прайса).
  const rows = form.value.checklist || []
  const same = rows.filter((r) => r.item_unit === unit.item_unit)
  const row = rows.find((r) => r.barcode && r.barcode === plain) || same.find((r) => lineByRow(r)) || same[0]
  let pack = null
  if (tracksExpiry.value) {
    if (unit.scanned_expiry) pack = { expiry: unit.scanned_expiry, series: unit.scanned_series || '' }
    else {
      const options = await knownPacks(unit, row?.item_unit ? row.expiry : null)
      pack = await askExpiry(unit, options)
      if (!pack) return
    }
  }
  if (row && row.item_unit) {
    if (!lineByRow(row)) {
      await tickRow(row, '1')
      // Срок с самой пачки (или выбранный) точнее, чем срок из старого файла.
      const ticked = lineByRow(row)
      if (ticked && pack) Object.assign(ticked, { expiry_date: pack.expiry, series: pack.series })
    } else {
      // Та же партия — +1; другой срок — ещё одна строка той же позиции файла.
      const rowUnit = { ...unit, item: row.item, item_unit: row.item_unit, item_name: row.item_name,
        unit_name: row.unit_name, base_unit: row.base_unit, ratio: row.ratio }
      await addPack(unit.item === row.item ? unit : rowUnit, pack, row.row)
    }
    panel.value?.reveal(row)
    return
  }
  addPack(unit, pack)
}

// Незнакомый код: это знакомый препарат в другой коробке — выбрать его, код запомнится.
const unknown = ref(null)
function unknownCode(code) {
  if (!can('catalog.change_item')) {
    return $q.notify({ type: 'warning', message: `Товар со штрихкодом ${code} не найден. Найдите его по названию.` })
  }
  unknown.value = { code, picked: null, found: [], error: '' }
}
async function searchUnknown(text, update, abort) {
  if (text.trim().length < 2) return update(() => (unknown.value.found = []))
  const { ok, data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (unknown.value.found = data.map((u) => ({ ...u, label: `${u.item_name} — ${u.unit_name}` }))))
}
async function rememberCode() {
  const { code, picked } = unknown.value
  busy.value = 'barcode'
  const { ok, data } = await apiPost('inventory/stock/add_barcode/', { item_unit: picked, code })
  busy.value = ''
  if (!ok) return (unknown.value.error = Object.values(fieldErrors(data))[0] || 'Не удалось запомнить код')
  unknown.value = null
  $q.notify({ type: 'positive', message: `Код ${data.code} запомнен — дальше сканер найдёт эту упаковку` })
  barcode.value = code
  await scan()
}

// --- Список из файла склада ------------------------------------------------------
const lineByRow = (row) => form.value.lines.find((l) => l.checklist_row === row.row)

async function loadChecklist(file) {
  if (!file) return
  busy.value = 'checklist'
  if (!form.value.id && !(await save(true, false))) return (busy.value = '')
  const payload = new FormData()
  payload.append('file', file)
  const { ok, data } = await apiUpload(`inventory/documents/${form.value.id}/checklist/`, payload)
  busy.value = ''
  checklistFile.value = null
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось прочитать файл')
  form.value.checklist = data.checklist
  form.value.checklist_name = data.checklist_name
  const s = data.checklist_summary
  $q.notify({ type: 'positive', timeout: 6000,
    message: `Позиций: ${s.total}. По штрихкоду: ${s.barcode}, по названию: ${s.name}, похожие: ${s.similar}, нет в прайсе: ${s.missing}` })
  if (props.id === 'new') router.replace(`/inventory/documents/${form.value.id}`)
}

async function tickRow(row, quantity) {
  if (!row.item_unit || lineByRow(row)) return
  const units = await unitsOf(row.item, row.item_name)
  form.value.lines.unshift({
    item: row.item, item_name: row.item_name, base_unit: row.base_unit, item_unit: row.item_unit,
    units: units.length ? units : [{ item_unit: row.item_unit, unit_name: row.unit_name, ratio: row.ratio }],
    quantity: quantity ?? row.qty_file ?? '1', price: null, series: '', expiry_date: row.expiry || null, batch: null,
    batches: [], qty_expected: null, checklist_row: row.row,
  })
}

function untickRow(row) {
  form.value.lines = form.value.lines.filter((l) => l.checklist_row !== row.row)
}

function pickRow(row, unit) {
  Object.assign(row, {
    match: 'manual', item: unit.item, item_unit: unit.item_unit, item_name: unit.item_name, unit_name: unit.unit_name,
    base_unit: unit.base_unit || row.base_unit, ratio: unit.ratio || row.ratio,
  })
  const line = lineByRow(row)
  if (line) untickRow(row)
}

async function saveBarcodes() {
  busy.value = 'barcodes'
  if (!(await save(true, false))) return (busy.value = '')
  const { ok, data } = await apiPost(`inventory/documents/${form.value.id}/checklist_barcodes/`)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось записать штрихкоды')
  form.value.checklist = data.checklist
  $q.notify({ type: data.skipped.length ? 'warning' : 'positive', timeout: 8000,
    message: `Записано штрихкодов: ${data.saved}`
      + (data.skipped.length ? `. Пропущено ${data.skipped.length}: ${data.skipped.slice(0, 3).join('; ')}` : '') })
}

function clearChecklist() {
  $q.dialog({
    title: 'Убрать список из файла?', message: 'Строки, которые уже попали в документ, останутся.',
    cancel: { label: 'Отмена', flat: true }, ok: { label: 'Убрать', color: 'primary', unelevated: true },
  }).onOk(async () => {
    if (!(await save(true, false))) return
    const { ok, data } = await apiPost(`inventory/documents/${form.value.id}/checklist_clear/`)
    if (ok) Object.assign(form.value, { checklist: data.checklist, checklist_name: data.checklist_name })
  })
}

async function searchItems(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (found.value = data.map((u) => ({ ...u, label: `${u.item_name} — ${u.unit_name} (на складе ${u.stock_text})` }))))
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
  line.batches = (data ?? []).map((b) => ({ ...b, label: `${b.label} · остаток ${b.qty_text}` }))
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
      checklist_row: l.checklist_row ?? null,
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

const departments = ref([])
onMounted(async () => {
  apiGet('inventory/departments/?active=true').then(({ data }) => (departments.value = data ?? []))
  const [w, c, g] = await Promise.all([
    apiGet('inventory/warehouses/?active=true'), apiGet('core/counterparties/?active=true&use=receipt'),
    apiGet('catalog/groups/?active=true&kind=goods'),
  ])
  warehouses.value = w.data ?? []
  counterparties.value = c.data ?? []
  groups.value = g.data ?? []
  if (props.id === 'new') {
    form.value = { kind: route.query.kind || 'receipt', date: new Date().toISOString(), warehouse: warehouses.value[0]?.id ?? null,
      target_warehouse: null, counterparty: null, supplier_number: '', supplier_date: null, reason: '', department: null, comment: '', lines: [], checklist: [] }
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
