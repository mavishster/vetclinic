<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 720px; max-width: 96vw">
      <q-card-section class="text-h6">Штрихкоды и этикетки</q-card-section>
      <q-card-section class="q-pt-none">
        <div class="text-caption text-grey-7 q-mb-sm">
          Отметьте единицы. У кого штрихкода нет, получат внутренний (начинается с «20», с кодами производителей
          не пересекается). Он запомнится в карточке, и сканер будет его узнавать. Свой код производителя не меняется.
        </div>
        <q-markup-table flat bordered dense wrap-cells>
          <thead>
            <tr>
              <th style="width: 40px"><q-checkbox :model-value="allState" dense @update:model-value="toggleAll" /></th>
              <th class="text-left">Позиция и единица</th>
              <th class="text-left">Штрихкод</th>
              <th style="width: 100px">Этикеток</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.item_unit">
              <td><q-checkbox v-model="row.checked" dense /></td>
              <td>{{ row.item_name }}<div class="text-caption text-grey-7">{{ row.unit_name }}</div></td>
              <td>
                <span v-if="row.barcode">{{ row.barcode }}<q-badge v-if="row.fresh" color="positive" label="новый" class="q-ml-xs" /></span>
                <span v-else class="text-grey-6">нет</span>
              </td>
              <td><q-input v-model.number="row.copies" type="number" min="1" dense borderless input-class="text-right" :disable="!row.checked" /></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="4" class="text-grey-7">У отмеченных позиций нет единиц товара</td></tr>
          </tbody>
        </q-markup-table>
        <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Закрыть" v-close-popup />
        <q-btn v-if="can('catalog.change_item')" outline color="primary" icon="qr_code_2" label="Присвоить штрихкоды"
          :disable="!toAssign.length" :loading="busy === 'assign'" @click="assign" />
        <q-btn unelevated color="primary" icon="print" label="Печать этикеток" :disable="!checked.length"
          :loading="busy === 'print'" @click="print" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Отмеченным товарам: присвоить внутренние штрихкоды тем единицам, у которых их нет,
// и напечатать этикетки (печать сама присваивает код, если его нет).
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiPost, fieldErrors, openPostedFile } from '@/api'
import { can } from '@/session'

const props = defineProps({ modelValue: Boolean, items: { type: Array, default: () => [] } })
const emit = defineEmits(['update:modelValue', 'changed'])
const $q = useQuasar()
const rows = ref([])
const busy = ref('')
const error = ref('')

const checked = computed(() => rows.value.filter((r) => r.checked))
const toAssign = computed(() => checked.value.filter((r) => !r.barcode))
const allState = computed(() => (checked.value.length === 0 ? false : checked.value.length === rows.value.length ? true : null))
const toggleAll = (value) => rows.value.forEach((r) => (r.checked = !!value))

watch(() => props.modelValue, (open) => {
  if (!open) return
  error.value = ''
  rows.value = props.items.filter((item) => item.kind === 'goods').flatMap((item) => {
    const units = [...(item.units || [])].sort((a, b) => Number(b.ratio) - Number(a.ratio))
    const hasCode = units.some((u) => u.barcode || u.extra_barcodes?.length)
    // По умолчанию — самая крупная единица (упаковка) товара без единого штрихкода.
    return units.map((u, index) => ({
      item_unit: u.id, item_name: item.name, unit_name: u.unit_name, barcode: u.barcode || '',
      checked: !hasCode && index === 0, copies: 1, fresh: false,
    }))
  })
})

async function assign() {
  error.value = ''
  busy.value = 'assign'
  const { ok, data } = await apiPost('catalog/items/assign-barcodes/', { units: toAssign.value.map((r) => r.item_unit) })
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось присвоить штрихкоды')
  for (const unit of data.units) {
    const row = rows.value.find((r) => r.item_unit === unit.item_unit)
    if (row) Object.assign(row, { barcode: unit.barcode, fresh: unit.new })
  }
  $q.notify({ type: 'positive', message: `Присвоено штрихкодов: ${data.assigned}` })
  emit('changed')
}

async function print() {
  error.value = ''
  busy.value = 'print'
  const lines = checked.value.map((r) => ({ item_unit: r.item_unit, copies: Math.max(1, Number(r.copies) || 1) }))
  const { ok, data } = await openPostedFile('inventory/labels/', { lines })
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось напечатать этикетки')
  emit('changed')  // печать присвоила коды тем, у кого их не было
}
</script>
