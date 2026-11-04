<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Перемещение на оперативный</h1>
    </div>
    <div class="row q-col-gutter-sm q-mb-md">
      <q-select v-model="from" :options="warehouses" option-value="id" option-label="name" emit-value map-options outlined dense
        label="Откуда" class="col-6 col-md-3" @update:model-value="lines = []" />
      <q-select v-model="to" :options="warehouses" option-value="id" option-label="name" emit-value map-options outlined dense
        label="Куда" class="col-6 col-md-3" />
      <q-input ref="scanner" v-model="code" outlined dense autofocus class="col-12 col-md-6" label="Сканер: штрихкод или DataMatrix + Enter"
        :loading="scanning" @keyup.enter="scan">
        <template #prepend><q-icon name="qr_code_scanner" /></template>
      </q-input>
    </div>
    <div v-if="error" class="text-negative q-mb-sm">{{ error }}</div>

    <q-card v-for="(line, index) in lines" :key="line.item_unit" flat bordered class="q-mb-sm">
      <q-card-section class="row items-center q-py-sm">
        <div class="col">
          <div class="text-subtitle1">{{ line.item_name }} <span class="text-caption text-grey-7">· {{ line.unit }}</span></div>
          <div class="text-caption text-grey-7">
            На «{{ warehouseName(to) }}» сейчас: {{ qty(line.on_target) }} {{ line.base_unit }}
            <span v-if="line.ratio !== '1.000'"> · 1 {{ line.unit }} = {{ qty(line.ratio) }} {{ line.base_unit }}</span>
          </div>
        </div>
        <q-input v-model.number="line.quantity" type="number" min="0" step="1" outlined dense style="width: 120px" :suffix="line.unit"
          :error="overdraft(line)" :error-message="`всего есть ${qty(totalOf(line))}`" no-error-icon
          :hint="spills(line) ? 'из нескольких партий — сначала ранние' : ''" />
        <q-btn flat round dense icon="close" class="q-ml-sm" @click="lines.splice(index, 1)" />
      </q-card-section>
      <q-separator />
      <q-list dense>
        <q-item v-for="b in line.batches" :key="b.batch" tag="label" :class="{ 'row-highlight-positive': b.batch === line.recommended }">
          <q-item-section side><q-radio v-model="line.batch" :val="b.batch" dense @update:model-value="checkBatch(line)" /></q-item-section>
          <q-item-section>
            <q-item-label>
              {{ b.series ? `Серия ${b.series}` : 'Без серии' }}
              <span :class="expiryClass(b.expiry_date)"> · {{ b.expiry_date ? `годен до ${fmt(b.expiry_date)}` : 'срок не указан' }}</span>
              <q-badge v-if="b.batch === line.recommended" color="positive" label="ранний срок — берите эту" class="q-ml-sm" />
              <q-badge v-if="b.batch === line.scanned_batch" color="primary" outline label="отсканирована" class="q-ml-xs" />
            </q-item-label>
          </q-item-section>
          <q-item-section side>{{ qty(b.qty_unit) }} {{ line.unit }}</q-item-section>
        </q-item>
        <q-item v-if="!line.batches.length"><q-item-section class="text-negative">На складе «{{ warehouseName(from) }}» этого товара нет</q-item-section></q-item>
      </q-list>
    </q-card>
    <div v-if="!lines.length" class="text-grey-7">
      Сканируйте упаковки по одной: каждое сканирование — +1. Система предложит партию с ближайшим сроком годности.
    </div>

    <div v-if="lines.length" class="row items-center q-mt-md q-gutter-sm">
      <q-space />
      <q-btn flat label="Очистить" @click="lines = []" />
      <q-btn color="primary" unelevated icon="move_down" :label="`Переместить (${lines.length})`" :loading="saving" :disable="!canSave" @click="save" />
    </div>
  </q-page>
</template>

<script setup>
// Перемещение со склада хранения на оперативный — по сканеру, с подсказкой партии
// с ближайшим сроком годности и предупреждением, если выбрана более поздняя.
import { computed, nextTick, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'

const $q = useQuasar()
const warehouses = ref([])
const from = ref(null)
const to = ref(null)
const code = ref('')
const lines = ref([])
const scanning = ref(false)
const saving = ref(false)
const error = ref('')
const scanner = ref(null)
const qty = (v) => Number(v || 0).toLocaleString('ru-RU', { maximumFractionDigits: 3 })
const fmt = (d) => new Date(d).toLocaleDateString('ru-RU')
const warehouseName = (id) => warehouses.value.find((w) => w.id === id)?.name || ''
const chosen = (line) => line.batches.find((b) => b.batch === line.batch)
const totalOf = (line) => line.batches.reduce((sum, b) => sum + Number(b.qty_unit), 0)
const overdraft = (line) => Number(line.quantity) > totalOf(line)
// Больше, чем в выбранной партии, — берём из нескольких партий по сроку (ранние первыми).
const spills = (line) => !!chosen(line) && Number(line.quantity) > Number(chosen(line).qty_unit) && !overdraft(line)
const canSave = computed(() => lines.value.every((l) => l.batch && Number(l.quantity) > 0 && !overdraft(l)) && from.value !== to.value)

function expiryClass(expiry) {
  if (!expiry) return 'text-grey-7'
  const days = (new Date(expiry) - new Date()) / 86400000
  return days < 0 ? 'text-negative' : days < 90 ? 'text-warning' : 'text-grey-8'
}

async function scan() {
  const value = code.value.trim()
  if (!value) return
  error.value = ''
  scanning.value = true
  const params = new URLSearchParams({ code: value, from: from.value, to: to.value })
  const { ok, data } = await apiGet(`inventory/transfer/?${params}`)
  scanning.value = false
  code.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось найти')
  const existing = lines.value.find((l) => l.item_unit === data.item_unit)
  if (existing) existing.quantity = Number(existing.quantity) + 1
  else {
    // По DataMatrix — отсканированная партия; иначе — с ближайшим сроком.
    lines.value.unshift({ ...data, quantity: 1, batch: data.scanned_batch || data.recommended })
    const line = lines.value[0]
    if (data.scanned_batch && data.recommended && data.scanned_batch !== data.recommended) warnLater(line)
  }
  await nextTick()
  scanner.value?.focus()
}

function warnLater(line) {
  const early = line.batches.find((b) => b.batch === line.recommended)
  $q.dialog({
    title: 'Есть партия с более ранним сроком',
    message: `${line.item_name}: на складе есть серия ${early.series || 'без серии'} — годна до ${fmt(early.expiry_date)}. Взять её вместо выбранной?`,
    cancel: { label: 'Оставить выбранную', flat: true }, ok: { label: 'Взять с ранним сроком', color: 'primary', unelevated: true },
  }).onOk(() => (line.batch = line.recommended))
}

function checkBatch(line) {
  const picked = chosen(line)
  const early = line.batches.find((b) => b.batch === line.recommended)
  if (picked && early && picked.batch !== early.batch && early.expiry_date && picked.expiry_date > early.expiry_date) warnLater(line)
}

async function save() {
  saving.value = true
  const { ok, data } = await apiPost('inventory/transfer/', {
    from: from.value, to: to.value,
    lines: lines.value.map((l) => ({ item_unit: l.item_unit, quantity: l.quantity, batch: spills(l) ? null : l.batch })),
  })
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось переместить')
  $q.notify({ type: 'positive', message: `Перемещено: документ № ${data.number}` })
  lines.value = []
  scanner.value?.focus()
}

onMounted(async () => {
  warehouses.value = (await apiGet('inventory/warehouses/?active=true')).data ?? []
  from.value = warehouses.value.find((w) => w.kind === 'storage')?.id ?? null
  to.value = warehouses.value.find((w) => w.kind === 'sale')?.id ?? null
})
</script>
