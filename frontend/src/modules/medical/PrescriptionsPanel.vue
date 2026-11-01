<template>
  <div>
    <q-markup-table flat bordered dense wrap-cells>
      <thead>
        <tr>
          <th class="text-left" style="min-width: 220px">Препарат</th><th class="text-left">Доза</th>
          <th class="text-left">Способ</th><th class="text-left">Кратность</th><th>Дней</th>
          <th class="text-left">Примечание</th><th class="text-left">Продать</th><th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="i">
          <td>
            <q-select v-model="row.item" :options="row.options" option-value="id" option-label="name" emit-value map-options
              use-input fill-input hide-selected input-debounce="300" dense borderless :readonly="!canEdit"
              :input-value="row.drug_name" placeholder="из прайса или своё название"
              @filter="(text, update, abort) => search(row, text, update, abort)"
              @input-value="(text) => onTyped(row, text)" @update:model-value="(id) => onPicked(row, id)" />
          </td>
          <td style="width: 90px"><q-input v-model="row.dose" dense borderless placeholder="1 таб." :readonly="!canEdit" /></td>
          <td style="width: 140px">
            <q-select v-model="row.route" :options="ROUTES" emit-value map-options dense borderless :readonly="!canEdit" />
          </td>
          <td style="width: 140px"><q-input v-model="row.frequency" dense borderless placeholder="2 раза в день" :readonly="!canEdit" /></td>
          <td style="width: 60px"><q-input v-model.number="row.days" type="number" min="1" dense borderless input-class="text-center" :readonly="!canEdit" /></td>
          <td><q-input v-model="row.comment" dense borderless placeholder="после еды" :readonly="!canEdit" /></td>
          <td style="width: 150px">
            <div v-if="row.units.length" class="row no-wrap items-center q-gutter-x-xs">
              <q-input v-model="row.sell_qty" type="number" min="0" step="1" dense borderless style="width: 48px"
                input-class="text-right" placeholder="0" :readonly="!canEdit" />
              <q-select v-model="row.sell_unit" :options="row.units" option-value="id" option-label="unit_name" emit-value
                map-options dense borderless :readonly="!canEdit" />
            </div>
            <span v-else class="text-caption text-grey-6">—</span>
          </td>
          <td class="text-right">
            <q-btn v-if="canEdit" flat round dense size="sm" icon="close" @click="rows.splice(i, 1); changed()" />
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="8" class="text-grey-7">Назначений нет</td></tr>
      </tbody>
    </q-markup-table>
    <div class="row items-center q-mt-sm q-gutter-sm">
      <q-btn v-if="canEdit" flat dense no-caps color="primary" icon="add" label="Назначение" @click="add" />
      <q-space />
      <span class="text-caption text-grey-7">{{ state }}</span>
      <q-btn v-if="canEdit" outline dense color="primary" icon="save" label="Сохранить" :loading="saving" @click="save" />
      <q-btn flat dense icon="print" label="Памятка владельцу" @click="print" />
    </div>
    <div class="text-caption text-grey-7 q-mt-xs">
      «Продать» — сколько препарата отпускаете на руки: он попадёт в счёт по этой записи вместе с отмеченным через «@».
    </div>
    <div v-if="error" class="text-negative q-mt-xs">{{ error }}</div>
  </div>
</template>

<script setup>
// Структурированные назначения: препарат (из прайса или название), доза, способ, кратность,
// сколько дней; «продать» — в счёт. Памятка владельцу печатается одной кнопкой.
import { ref, watch } from 'vue'
import { apiGet, apiPut, fieldErrors } from '@/api'

const props = defineProps({ visit: { type: Object, required: true }, canEdit: { type: Boolean, default: false } })
const emit = defineEmits(['changed'])
const ROUTES = [
  { value: 'oral', label: 'внутрь' }, { value: 'sc', label: 'подкожно' }, { value: 'im', label: 'внутримышечно' },
  { value: 'iv', label: 'внутривенно' }, { value: 'topical', label: 'наружно' }, { value: 'eyes', label: 'в глаза' },
  { value: 'ears', label: 'в уши' }, { value: 'rectal', label: 'ректально' }, { value: 'other', label: 'другое' },
]
const rows = ref([])
const saving = ref(false)
const state = ref('')
const error = ref('')

function toRow(p) {
  return {
    item: p.item, drug_name: p.drug_name, dose: p.dose, route: p.route, frequency: p.frequency, days: p.days,
    comment: p.comment, sell_unit: p.sell_unit, sell_qty: p.sell_qty ? Number(p.sell_qty) : null,
    options: p.item ? [{ id: p.item, name: p.drug_name }] : [],
    units: p.sell_unit ? [{ id: p.sell_unit, unit_name: p.sell_unit_name }] : [],
  }
}
watch(() => props.visit.id, () => (rows.value = (props.visit.prescriptions || []).map(toRow)), { immediate: true })

const changed = () => (state.value = 'есть несохранённые изменения')
watch(rows, changed, { deep: true, flush: 'post' })
setTimeout(() => (state.value = ''), 0)

function add() {
  rows.value.push({ item: null, drug_name: '', dose: '', route: 'oral', frequency: '', days: null, comment: '', sell_unit: null, sell_qty: null, options: [], units: [] })
}

async function search(row, text, update, abort) {
  if (text.trim().length < 2) return update(() => (row.options = []))
  const { ok, data } = await apiGet(`catalog/items/?kind=goods&active=true&page_size=15&search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => (row.options = (data.results || []).map((i) => ({ id: i.id, name: i.name, units: i.units.filter((u) => u.for_sale) }))))
}

// Набрали своё название, не выбирая из прайса — это просто текст назначения.
function onTyped(row, text) {
  row.drug_name = text
  if (row.item && row.options.find((o) => o.id === row.item)?.name !== text) {
    row.item = null
    row.units = []
    row.sell_unit = null
  }
}

function onPicked(row, id) {
  const option = row.options.find((o) => o.id === id)
  row.drug_name = option?.name || row.drug_name
  row.units = option?.units || []
  row.sell_unit = row.units[0]?.id || null
}

async function save() {
  error.value = ''
  saving.value = true
  const body = rows.value.filter((r) => r.item || r.drug_name.trim()).map((r) => ({
    item: r.item, drug_name: r.drug_name, dose: r.dose, route: r.route, frequency: r.frequency, days: r.days || null,
    comment: r.comment, sell_unit: r.sell_qty ? r.sell_unit : null, sell_qty: r.sell_qty || null,
  }))
  const { ok, data } = await apiPut(`medical/visits/${props.visit.id}/prescriptions/`, { rows: body })
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  emit('changed', data)
  rows.value = data.prescriptions.map(toRow)
  setTimeout(() => (state.value = 'сохранено'), 0)
}

async function print() {
  if (props.canEdit && state.value.startsWith('есть')) await save()
  window.open(`/api/medical/visits/${props.visit.id}/print-prescriptions/`, '_blank')
}
</script>
