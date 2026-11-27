<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 760px; max-width: 96vw">
      <q-card-section class="text-h6">Объединить {{ items.length }} позиции в одну</q-card-section>
      <q-card-section class="q-pt-none">
        <div class="text-caption text-grey-7 q-mb-sm">
          Счета, медкарты, черновики склада и комбинации перейдут на основную позицию, остальные удалятся.
          Суммы в счетах не меняются.
        </div>

        <div class="text-subtitle2">Основная позиция</div>
        <q-option-group v-model="mainId" :options="items.map((i) => ({ label: i.name, value: i.id }))" dense class="q-mb-md" />

        <div class="row q-col-gutter-sm q-mb-md">
          <q-input v-model="name" outlined dense label="Название после объединения" class="col-12 col-sm-8" />
          <q-select v-model="baseUnit" :options="units" option-value="id" option-label="name" emit-value map-options
            outlined dense label="Единица учёта" hint="В ней остаток на складе — самая мелкая" class="col-12 col-sm-4" />
        </div>

        <div class="text-subtitle2">Чем станет каждая единица</div>
        <q-markup-table flat bordered dense wrap-cells class="q-mb-sm">
          <tbody>
            <tr v-for="row in rows" :key="row.item_unit">
              <td>
                <div>{{ row.item_name }}</div>
                <div class="text-caption text-grey-7">{{ row.unit_name }}{{ row.price ? ` · ${money(row.price)}` : '' }}</div>
              </td>
              <td style="width: 150px">
                <q-select v-model="row.unit" :options="units" option-value="id" option-label="name" emit-value map-options dense borderless />
              </td>
              <td style="width: 170px">
                <q-input v-if="row.unit !== baseUnit" v-model="row.ratio" type="number" step="any" min="0" dense borderless
                  input-class="text-right" :prefix="'='" :suffix="baseName" />
                <span v-else class="text-grey-7">= 1 {{ baseName }}</span>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
        <div class="text-caption text-grey-7">
          Например, учёт в таблетках: таблетка = 1 таб., упаковка из 4 таблеток = 4 таб.
        </div>

        <div v-if="preview" class="q-mt-md">
          <div class="text-subtitle2">Что изменится</div>
          <div v-if="!preview.changes.length" class="text-grey-7">Ссылок на эти позиции нет — просто объединятся.</div>
          <div v-for="c in preview.changes" :key="c.title">{{ c.title }}: <b>{{ c.count }}</b></div>
          <div class="q-mt-xs">Единицы: {{ preview.units.map((u) => `${u.unit} = ${u.ratio} ${baseName}`).join(', ') }}</div>
        </div>
        <div v-if="error" class="text-negative q-mt-md">{{ error }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn outline color="primary" label="Проверить" :loading="busy === 'check'" @click="check" />
        <q-btn unelevated color="primary" icon="merge" label="Объединить" :disable="!preview" :loading="busy === 'merge'" @click="confirm" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Объединение позиций прайса, в том числе уже использованных в счетах (ADR-026).
// Сначала «Проверить» — сервер считает, что изменится; «Объединить» — после проверки.
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { money } from './money'

const props = defineProps({ modelValue: Boolean, items: { type: Array, default: () => [] } })
const emit = defineEmits(['update:modelValue', 'merged'])
const $q = useQuasar()
const units = ref([])
const mainId = ref(null)
const name = ref('')
const baseUnit = ref(null)
const rows = ref([])
const preview = ref(null)
const error = ref('')
const busy = ref('')

// Самые мелкие единицы — кандидаты в единицы учёта.
const PIECES = ['таб.', 'капс.', 'мл', 'шт.', 'доза', 'амп.', 'саше', 'г', 'фл.']
const baseName = computed(() => units.value.find((u) => u.id === baseUnit.value)?.name || '')

// Сколько единиц учёта в позиции — из названия: «…, 4табл.» при учёте в «таб.» → 4.
function countInName(itemName, unitName) {
  const stem = unitName.replace('.', '').slice(0, 3)
  if (!stem) return null
  const match = itemName.match(new RegExp(`(\\d+[.,]?\\d*)\\s*${stem}`, 'i'))
  return match ? Number(match[1].replace(',', '.')) : null
}

function defaults() {
  for (const row of rows.value) {
    const item = props.items.find((i) => i.id === row.item)
    if (row.unit === baseUnit.value) row.ratio = '1'
    else if (item.base_unit === baseUnit.value) row.ratio = String(Number(row.old_ratio))
    else {
      const count = countInName(item.name, baseName.value)
      row.ratio = count ? String(count * Number(row.old_ratio)) : ''
    }
  }
}

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  preview.value = null
  if (!units.value.length) units.value = (await apiGet('catalog/units/?active=true')).data ?? []
  const items = props.items
  mainId.value = [...items].sort((a, b) => (b.units?.length || 0) - (a.units?.length || 0))[0]?.id ?? null
  name.value = items.find((i) => i.id === mainId.value)?.name || ''
  const pieceItem = items.find((i) => PIECES.includes(units.value.find((u) => u.id === i.base_unit)?.name))
  baseUnit.value = (pieceItem || items[0])?.base_unit ?? null
  rows.value = items.flatMap((item) => (item.units || []).map((u) => ({
    item: item.id, item_name: item.name, item_unit: u.id, unit_name: u.unit_name, price: u.current_price ?? u.price,
    unit: u.unit, old_ratio: u.ratio, ratio: '',
  })))
  defaults()
})

watch(mainId, (id) => { name.value = props.items.find((i) => i.id === id)?.name || name.value })
watch(baseUnit, () => defaults())
// Изменили план — прежняя проверка уже не про него.
watch([mainId, name, baseUnit, rows], () => { preview.value = null }, { deep: true })

function body(dryRun) {
  return {
    main: mainId.value, items: props.items.map((i) => i.id), name: name.value, base_unit: baseUnit.value, dry_run: dryRun,
    units: rows.value.map((r) => ({ item_unit: r.item_unit, unit: r.unit, ratio: r.unit === baseUnit.value ? '1' : r.ratio || '0' })),
  }
}

async function check() {
  error.value = ''
  busy.value = 'check'
  const { ok, data } = await apiPost('catalog/items/merge/', body(true))
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось проверить')
  preview.value = data
}

function confirm() {
  const others = props.items.filter((i) => i.id !== mainId.value).map((i) => `«${i.name}»`).join(', ')
  $q.dialog({
    title: 'Объединить позиции?',
    message: `Останется «${name.value}». Удалятся: ${others}. Отменить объединение кнопкой нельзя — проверьте единицы ещё раз.`,
    cancel: { label: 'Отмена', flat: true }, ok: { label: 'Объединить', color: 'primary', unelevated: true },
  }).onOk(async () => {
    busy.value = 'merge'
    const { ok, data } = await apiPost('catalog/items/merge/', body(false))
    busy.value = ''
    if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось объединить')
    $q.notify({ type: 'positive', message: `Объединено в «${data.item.name}»` })
    emit('update:modelValue', false)
    emit('merged', data.item)
  })
}
</script>
