<template>
  <q-card flat bordered class="q-mb-md">
    <q-card-section class="row items-center q-gutter-sm q-pb-sm">
      <q-icon name="checklist" color="primary" size="24px" />
      <div class="text-subtitle1">Список из файла <span class="text-grey-7">{{ name }}</span></div>
      <q-space />
      <q-btn v-if="!executed && canBarcodes && barcodeCount" outline color="primary" icon="qr_code" dense no-caps
        :label="`Записать штрихкоды в прайс (${barcodeCount})`" :loading="busy" @click="emit('barcodes')">
        <q-tooltip>Позициям, совпавшим по названию или отмеченным на полке, — штрихкод из файла.
          Дальше товар находится сканером везде.</q-tooltip>
      </q-btn>
      <q-btn v-if="!executed" flat dense color="grey-8" icon="close" label="Убрать список" no-caps @click="emit('clear')" />
    </q-card-section>

    <q-card-section class="q-pt-none">
      <div class="row items-center q-gutter-sm q-mb-sm">
        <div class="text-body2">Отмечено <b>{{ tickedCount }}</b> из {{ rows.length }}</div>
        <q-linear-progress :value="rows.length ? tickedCount / rows.length : 0" color="positive" track-color="orange-2"
          rounded size="10px" class="col" />
      </div>
      <div class="row q-col-gutter-sm items-center">
        <q-input v-model="search" dense outlined clearable debounce="150" placeholder="Поиск по названию или штрихкоду"
          class="col-12 col-sm-5"><template #prepend><q-icon name="search" /></template></q-input>
        <div class="col-12 col-sm">
          <q-btn-toggle v-model="filter" dense no-caps unelevated toggle-color="primary" color="grey-3" text-color="grey-9"
            :options="filters" />
        </div>
      </div>
      <div class="text-caption text-grey-7 q-mt-xs">
        Нашли на полке — отметьте строку: количество подставится из файла, исправьте, если на полке иначе.
        Сканер сам находит и отмечает строку, каждое сканирование — плюс одна упаковка.
        <span class="checklist-legend bg-orange-1">не отмечено</span>
        <span class="checklist-legend bg-green-1">отмечено</span>
      </div>
    </q-card-section>

    <q-table :rows="shown" :columns="columns" row-key="row" flat dense virtual-scroll :rows-per-page-options="[0]"
      hide-pagination style="max-height: 460px" class="checklist-table" no-data-label="Ничего не найдено">
      <template #body="props">
        <q-tr :props="props" :id="`checklist-row-${props.row.row}`"
          :class="[lineOf(props.row) ? 'bg-green-1' : 'bg-orange-1', props.row.row === flash ? 'checklist-flash' : '']">
          <q-td key="tick" :props="props" style="width: 40px">
            <q-checkbox :model-value="!!lineOf(props.row)" dense :disable="executed || !props.row.item_unit"
              @update:model-value="(v) => (v ? tick(props.row) : emit('untick', props.row))" />
          </q-td>
          <q-td key="name" :props="props" style="white-space: normal; min-width: 220px">
            <div>{{ props.row.name }}</div>
            <div class="text-caption text-grey-7">
              {{ props.row.barcode || 'без штрихкода' }}<template v-if="props.row.section"> · {{ props.row.section }}</template>
            </div>
          </q-td>
          <q-td key="expiry" :props="props">{{ dateText(props.row.expiry) }}</q-td>
          <q-td key="file" :props="props" class="text-grey-8">
            {{ props.row.qty_file ?? '—' }} {{ props.row.unit_text }}
          </q-td>
          <q-td key="item" :props="props" style="white-space: normal; min-width: 240px">
            <div class="row items-center no-wrap q-gutter-xs">
              <q-badge :color="badge(props.row).color" :label="badge(props.row).label" />
              <div class="col">
                <template v-if="props.row.item_unit">{{ props.row.item_name }}
                  <span class="text-grey-7">· {{ props.row.unit_name }}</span></template>
                <span v-else class="text-negative">нет в прайсе — выберите</span>
              </div>
              <q-btn v-if="!executed" flat round dense size="sm" icon="edit" @click="startPick(props.row)">
                <q-tooltip>Выбрать позицию прайса</q-tooltip>
              </q-btn>
            </div>
            <q-select v-if="picking === props.row.row" autofocus dense outlined use-input input-debounce="300" class="q-mt-xs"
              :options="pickOptions(props.row)" option-value="item_unit" option-label="label" emit-value map-options
              label="Позиция прайса" @filter="searchItems" @update:model-value="(id) => pick(props.row, id)"
              @blur="picking = null" />
          </q-td>
          <q-td key="counted" :props="props" style="width: 120px">
            <q-input v-if="lineOf(props.row)" v-model="lineOf(props.row).quantity" type="number" step="any" min="0" dense
              borderless input-class="text-right text-weight-medium" :readonly="executed" :suffix="unitOfLine(props.row)" />
          </q-td>
        </q-tr>
      </template>
    </q-table>
  </q-card>
</template>

<script setup>
// Список из старого файла склада рядом с документом инвентаризации: что искать на полке.
// Отмеченная строка — строка документа (по номеру строки файла), неотмеченные подсвечены.
import { computed, nextTick, ref, watch } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({
  rows: { type: Array, required: true },
  lines: { type: Array, required: true },
  name: { type: String, default: '' },
  executed: { type: Boolean, default: false },
  canBarcodes: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['tick', 'untick', 'pick', 'barcodes', 'clear'])

const search = ref('')
const filter = ref('todo')
const picking = ref(null)
const found = ref([])
const flash = ref(null)
// Отмеченные только что не исчезают из «Не отмечены» — чтобы поправить количество.
const recent = ref(new Set())
watch([search, filter], () => (recent.value = new Set()))
const filters = [
  { label: 'Не отмечены', value: 'todo' },
  { label: 'Отмечены', value: 'done' },
  { label: 'Нет в прайсе', value: 'missing' },
  { label: 'Похожие', value: 'similar' },
  { label: 'Все', value: 'all' },
]
const columns = [
  { name: 'tick', label: '', align: 'left' },
  { name: 'name', label: 'В файле', align: 'left' },
  { name: 'expiry', label: 'Годен до', align: 'left' },
  { name: 'file', label: 'Было', align: 'right' },
  { name: 'item', label: 'В прайсе', align: 'left' },
  { name: 'counted', label: 'Насчитано', align: 'right' },
]

const byRow = computed(() => new Map(props.lines.filter((l) => l.checklist_row != null).map((l) => [l.checklist_row, l])))
const lineOf = (row) => byRow.value.get(row.row)
const tickedCount = computed(() => props.rows.filter((r) => byRow.value.has(r.row)).length)
const barcodeCount = computed(() => props.rows.filter((r) => r.barcode && r.item_unit && r.match !== 'barcode'
  && (r.match === 'name' || r.match === 'manual' || byRow.value.has(r.row))).length)

const shown = computed(() => {
  const text = (search.value || '').trim().toLowerCase()
  return props.rows.filter((r) => {
    if (text && !`${r.name} ${r.barcode} ${r.item_name}`.toLowerCase().includes(text)) return false
    const done = byRow.value.has(r.row)
    if (filter.value === 'todo') return !done || recent.value.has(r.row)
    if (filter.value === 'done') return done
    if (filter.value === 'missing') return !r.item_unit
    if (filter.value === 'similar') return r.match === 'similar'
    return true
  })
})

const BADGES = {
  barcode: { color: 'positive', label: 'штрихкод' },
  name: { color: 'primary', label: 'название' },
  manual: { color: 'primary', label: 'вручную' },
  similar: { color: 'warning', label: 'похоже?' },
}
const badge = (row) => BADGES[row.match] || { color: 'negative', label: 'нет' }
const dateText = (value) => (value ? new Date(value).toLocaleDateString('ru-RU') : '—')
function unitOfLine(row) {
  const line = lineOf(row)
  return line?.units?.find((u) => u.item_unit === line.item_unit)?.unit_name || row.unit_name
}

function tick(row) {
  recent.value.add(row.row)
  emit('tick', row)
}

function startPick(row) {
  picking.value = row.row
  found.value = []
}
function pickOptions(row) {
  const suggested = (row.candidates || []).map((c) => ({ ...c, label: `${c.item_name} — ${c.unit_name} (похоже)` }))
  return [...suggested, ...found.value]
}
async function searchItems(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (found.value = data.map((u) => ({ ...u, label: `${u.item_name} — ${u.unit_name}` }))))
}
function pick(row, id) {
  const unit = [...found.value, ...(row.candidates || [])].find((u) => u.item_unit === id)
  picking.value = null
  if (unit) emit('pick', row, unit)
}

// Строку, найденную сканером, показать и подсветить.
async function reveal(row) {
  recent.value.add(row.row)
  flash.value = row.row
  await nextTick()
  document.getElementById(`checklist-row-${row.row}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  setTimeout(() => { if (flash.value === row.row) flash.value = null }, 2500)
}
defineExpose({ reveal })
</script>

<style scoped>
.checklist-legend { display: inline-block; padding: 0 6px; margin-left: 6px; border-radius: 4px; }
.checklist-flash { outline: 2px solid var(--q-primary); }
</style>
