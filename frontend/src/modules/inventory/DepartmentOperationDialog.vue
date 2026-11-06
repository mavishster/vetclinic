<template>
  <q-dialog :model-value="modelValue" persistent :maximized="$q.screen.lt.md" @update:model-value="$emit('update:modelValue', $event)">
    <q-card style="width: 900px; max-width: 98vw">
      <q-card-section class="row items-center q-pb-sm">
        <q-icon :name="MODES[mode].icon" color="primary" size="sm" class="q-mr-sm" />
        <div class="text-h6 col">{{ MODES[mode].title }}</div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section class="q-pt-none">
        <div class="row q-col-gutter-sm">
          <q-select v-model="departmentId" :options="departments" option-value="id" option-label="name" emit-value map-options
            outlined dense label="Отделение *" class="col-12 col-sm-4" @update:model-value="onDepartment" />
          <q-input v-model="day" type="date" :max="today" outlined dense stack-label label="Дата" class="col-6 col-sm-3"
            hint="По умолчанию — сегодня" />
          <q-select v-if="mode !== 'count'" v-model="warehouseId" :options="warehouses" option-value="id" option-label="name" emit-value
            map-options outlined dense :label="mode === 'issue' ? 'С какого склада' : 'На какой склад'" class="col-6 col-sm-5" />
        </div>

        <q-banner v-if="mode === 'issue' && status?.count_pending" dense rounded class="row-highlight-warning q-mt-sm">
          <template #avatar><q-icon name="warning" color="warning" /></template>
          Остатки после выдачи {{ when(status.last_issue.date) }} ({{ status.last_issue.created_by || 'без автора' }}) ещё не внесены.
          Выдать можно, но расход по прошлой выдаче пока неизвестен.
        </q-banner>
        <div v-if="status && mode === 'count'" class="text-caption text-grey-7 q-mt-sm">
          Последняя выдача: {{ status.last_issue ? `${when(status.last_issue.date)} — ${status.last_issue.created_by}` : 'не было' }} ·
          последний пересчёт: {{ status.last_count ? `${when(status.last_count.date)} — ${status.last_count.created_by}` : 'не было' }}
        </div>

        <!-- Добавить материал: сканер или поиск по названию -->
        <div v-if="departmentId" class="row q-col-gutter-sm q-mt-sm items-center">
          <q-input v-model="code" outlined dense class="col-12 col-sm-4" label="Сканер: штрихкод + Enter" :loading="scanning" @keyup.enter="scan">
            <template #prepend><q-icon name="qr_code_scanner" /></template>
          </q-input>
          <q-select v-model="found" :options="options" option-label="label" use-input input-debounce="300" outlined dense clearable
            class="col-12 col-sm-5" label="Материал — начните вводить название" @filter="search" @update:model-value="addFound">
            <template #no-option><q-item><q-item-section class="text-grey-7">Введите 2 буквы названия</q-item-section></q-item></template>
          </q-select>
          <div class="col-12 col-sm-3 text-right">
            <q-btn v-if="mode === 'issue'" flat dense no-caps color="primary" icon="playlist_add" label="Пополнить до нормы" @click="toNorm" />
          </div>
        </div>
        <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <!-- Выдача и возврат: материал, единица (как в счёте), количество -->
        <q-markup-table v-if="mode !== 'count' && lines.length" flat bordered dense separator="horizontal">
          <thead><tr><th class="text-left">Материал</th><th class="text-left">Единица</th><th class="text-right">Количество</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(line, index) in lines" :key="line.item">
              <td>
                <div class="text-weight-medium">{{ line.item_name }}</div>
                <div class="text-caption text-grey-7">{{ line.hint }}</div>
              </td>
              <td style="width: 150px">
                <q-select v-model="line.item_unit" :options="line.units" option-value="item_unit" option-label="unit_name" emit-value map-options
                  dense borderless />
              </td>
              <td style="width: 120px"><q-input v-model="line.quantity" type="number" step="any" min="0" dense borderless input-class="text-right" /></td>
              <td style="width: 40px"><q-btn flat round dense icon="close" @click="lines.splice(index, 1)" /></td>
            </tr>
          </tbody>
        </q-markup-table>

        <!-- Внести остатки: сколько осталось — упаковками и штуками; пусто — не считали -->
        <template v-if="mode === 'count' && lines.length">
          <div class="text-caption text-grey-7 q-mb-xs">
            Введите, сколько осталось на самом деле. Пустое поле — материал не пересчитывали, его остаток не изменится.
            Недостача станет расходом отделения.
          </div>
          <q-markup-table flat bordered dense separator="horizontal">
            <thead><tr><th class="text-left">Материал</th><th class="text-right">По учёту</th><th class="text-right">Осталось на самом деле</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(line, index) in lines" :key="line.item">
                <td class="text-weight-medium">{{ line.item_name }}</td>
                <td class="text-right text-grey-8">{{ line.expected_text || '—' }}</td>
                <td style="width: 280px">
                  <div class="row no-wrap q-gutter-x-sm justify-end">
                    <q-input v-model="line.packQty" type="number" step="any" min="0" dense outlined style="width: 110px" :suffix="line.pack.unit_name" />
                    <q-input v-if="line.piece" v-model="line.pieceQty" type="number" step="any" min="0" dense outlined style="width: 110px"
                      :suffix="line.piece.unit_name" />
                  </div>
                </td>
                <td style="width: 40px"><q-btn v-if="line.added" flat round dense icon="close" @click="lines.splice(index, 1)" /></td>
              </tr>
            </tbody>
          </q-markup-table>
        </template>
        <div v-if="departmentId && !lines.length" class="text-grey-7">
          {{ mode === 'count' ? 'За отделением ничего не числится — добавьте материалы, которые есть на полке.' : 'Добавьте материалы сканером или поиском.' }}
        </div>
        <q-input v-model="comment" outlined dense autogrow label="Комментарий" class="q-mt-md" />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn color="primary" unelevated :icon="MODES[mode].icon" :label="MODES[mode].button" :loading="saving" :disable="!canSave" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Операции склада отделения (ADR-024): выдача с основного склада, внесение остатков (пересчёт),
// возврат на склад. Единица — любая у товара (упак., фл., таб.), как в счёте.
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'

const props = defineProps({
  modelValue: Boolean,
  mode: { type: String, default: 'issue' }, // issue | count | return
  department: { type: String, default: null },
  departments: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'done'])
const $q = useQuasar()

const MODES = {
  issue: { title: 'Выдача на отделение', button: 'Выдать', icon: 'move_down' },
  count: { title: 'Внести остатки отделения', button: 'Внести остатки', icon: 'fact_check' },
  return: { title: 'Возврат с отделения на склад', button: 'Вернуть', icon: 'assignment_return' },
}
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const today = iso(new Date())
const when = (v) => new Date(v).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

const departmentId = ref(null)
const day = ref(today)
const warehouses = ref([])
const warehouseId = ref(null)
const status = ref(null)
const lines = ref([])
const comment = ref('')
const code = ref('')
const found = ref(null)
const options = ref([])
const scanning = ref(false)
const saving = ref(false)
const error = ref('')
const balance = ref({}) // остаток отделения по товару — подсказка при возврате

const filled = (v) => v !== '' && v !== null && v !== undefined
const canSave = computed(() => {
  if (!departmentId.value) return false
  if (props.mode === 'count') return lines.value.some((l) => filled(l.packQty) || filled(l.pieceQty))
  return lines.value.length > 0 && lines.value.every((l) => l.item_unit && Number(l.quantity) > 0)
})

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  lines.value = []
  comment.value = ''
  day.value = today
  departmentId.value = props.department
  if (!warehouses.value.length) {
    warehouses.value = ((await apiGet('inventory/warehouses/?active=true')).data ?? [])
  }
  warehouseId.value = warehouses.value.find((w) => w.kind === 'storage')?.id ?? warehouses.value[0]?.id ?? null
  if (departmentId.value) onDepartment()
})

async function onDepartment() {
  lines.value = []
  status.value = (await apiGet(`inventory/department-stock/status/?department=${departmentId.value}`)).data
  const sheet = (await apiGet(`inventory/department-stock/sheet/?department=${departmentId.value}`)).data ?? []
  balance.value = Object.fromEntries(sheet.map((r) => [r.item, r.qty_text]))
  if (props.mode === 'count') lines.value = sheet.map((r) => countLine(r.item, r.item_name, r.units.map(unitOf), r.qty_text))
}

const unitOf = (u) => ({ item_unit: u.item_unit, unit_name: u.unit ?? u.unit_name, ratio: Number(u.ratio) })

// Строка пересчёта: поле упаковок и, если у товара есть штучная единица, — поле штук.
function countLine(item, name, units, expected = '', added = false) {
  const sorted = [...units].sort((a, b) => b.ratio - a.ratio)
  const pack = sorted[0]
  const piece = sorted.length > 1 ? sorted[sorted.length - 1] : null
  return { item, item_name: name, expected_text: expected, pack, piece, packQty: '', pieceQty: '', added }
}

async function unitsOfItem(item) {
  const { data } = await apiGet(`inventory/stock/lookup/?item=${item}`)
  return data ?? []
}

async function addItem(item, preferredUnit = null) {
  error.value = ''
  if (lines.value.some((l) => l.item === item)) return
  const rows = await unitsOfItem(item)
  if (!rows.length) return
  const units = rows.map(unitOf)
  const name = rows[0].item_name
  if (props.mode === 'count') {
    lines.value.push(countLine(item, name, units, balance.value[item] || '0', true))
    return
  }
  const hint = props.mode === 'issue' ? `на складах: ${rows[0].stock_text}` : `в отделении: ${balance.value[item] || 'нет'}`
  lines.value.unshift({ item, item_name: name, units, item_unit: preferredUnit || units[0].item_unit, quantity: 1, hint })
}

async function scan() {
  const value = code.value.trim()
  if (!value) return
  scanning.value = true
  const { data } = await apiGet(`inventory/stock/lookup/?barcode=${encodeURIComponent(value)}`)
  scanning.value = false
  code.value = ''
  const unit = (data ?? [])[0]
  if (!unit) return (error.value = 'Товар с таким штрихкодом не найден в прайсе')
  const line = lines.value.find((l) => l.item === unit.item)
  if (line && props.mode !== 'count') line.quantity = Number(line.quantity) + 1
  else await addItem(unit.item, unit.item_unit)
}

async function search(text, update, abort) {
  if (text.length < 2) return abort()
  const { data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  const items = new Map()
  for (const u of data ?? []) if (!items.has(u.item)) items.set(u.item, { item: u.item, label: `${u.item_name} · на складах ${u.stock_text}` })
  update(() => (options.value = [...items.values()]))
}

function addFound(option) {
  if (option) addItem(option.item)
  found.value = null
}

// «Пополнить до нормы»: строки на недостающее количество — в мелкой единице (таб., фл.).
async function toNorm() {
  const { data } = await apiGet(`inventory/department-stock/to-norm/?department=${departmentId.value}`)
  if (!data?.length) return $q.notify({ message: 'Все материалы с нормой — не ниже нормы' })
  for (const row of data) {
    const units = row.units.map(unitOf).sort((a, b) => a.ratio - b.ratio)
    const unit = units.find((u) => (Number(row.need) / u.ratio) % 1 === 0 && u.ratio > 1) || units[0]
    const existing = lines.value.find((l) => l.item === row.item)
    if (existing) continue
    lines.value.push({ item: row.item, item_name: row.item_name, units, item_unit: unit.item_unit,
      quantity: Number(row.need) / unit.ratio, hint: `до нормы не хватает ${row.need_text}` })
  }
}

function payloadLines() {
  if (props.mode !== 'count') return lines.value.map((l) => ({ item_unit: l.item_unit, quantity: l.quantity }))
  const result = []
  for (const l of lines.value) {
    if (!filled(l.packQty) && !filled(l.pieceQty)) continue
    result.push({ item_unit: l.pack.item_unit, quantity: filled(l.packQty) ? l.packQty : 0 })
    if (l.piece && filled(l.pieceQty)) result.push({ item_unit: l.piece.item_unit, quantity: l.pieceQty })
  }
  return result
}

async function save() {
  error.value = ''
  saving.value = true
  const step = { issue: 'issue', count: 'count', return: 'return' }[props.mode]
  const { ok, data } = await apiPost(`inventory/department-stock/${step}/`, {
    department: departmentId.value, date: day.value, warehouse: warehouseId.value, comment: comment.value, lines: payloadLines(),
  })
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  $q.notify({ type: 'positive', message: `${MODES[props.mode].title}: документ № ${data.number}` })
  emit('update:modelValue', false)
  emit('done')
  window.dispatchEvent(new Event('departments-changed'))
}
</script>
