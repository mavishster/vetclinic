<template>
  <div>
    <div class="row items-center q-mb-sm q-gutter-sm">
      <div class="text-caption text-grey-7 col">Товары, остаток которых ниже минимума. Минимум задаётся в единицах учёта.</div>
      <q-btn v-if="can('inventory.add_minstock')" outline color="primary" icon="add" label="Задать минимум" @click="open = true" />
    </div>
    <q-table :rows="rows" :columns="columns" row-key="rule" flat bordered :pagination="{ rowsPerPage: 50 }"
      no-data-label="Всего хватает" rows-per-page-label="Строк на странице" />

    <div class="text-subtitle2 q-mt-lg q-mb-xs">Заданные минимумы</div>
    <q-list bordered separator dense class="rounded-borders">
      <q-item v-for="rule in rules" :key="rule.id">
        <q-item-section>{{ rule.item_name }}</q-item-section>
        <q-item-section side>{{ Number(rule.min_qty) }} {{ rule.unit }} · {{ rule.warehouse_name }}</q-item-section>
        <q-item-section v-if="can('inventory.delete_minstock')" side>
          <q-btn flat round dense size="sm" icon="close" @click="remove(rule)"><q-tooltip>Убрать минимум</q-tooltip></q-btn>
        </q-item-section>
      </q-item>
      <q-item v-if="!rules.length"><q-item-section class="text-grey-7">Минимумы не заданы</q-item-section></q-item>
    </q-list>

    <q-dialog v-model="open">
      <q-card style="width: 460px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">Минимальный остаток</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <q-select v-model="form.item" :options="found" option-value="item" option-label="label" emit-value map-options use-input
              input-debounce="300" outlined dense label="Товар" @filter="search" />
            <q-select v-model="form.warehouse" :options="warehouses" option-value="id" option-label="name" emit-value map-options
              outlined dense clearable label="Склад (пусто — все склады)" />
            <q-input v-model="form.min_qty" type="number" step="0.001" min="0" outlined dense
              :label="`Минимум${unitName ? `, ${unitName}` : ''}`" />
            <div v-if="error" class="text-negative">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn type="submit" color="primary" unelevated label="Сохранить" :disable="!form.item || !form.min_qty" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
// «Нужно заказать»: товары ниже минимального остатка и сами минимумы.
import { computed, onMounted, ref } from 'vue'
import { apiDelete, apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({ warehouses: { type: Array, default: () => [] } })
const rows = ref([])
const rules = ref([])
const open = ref(false)
const found = ref([])
const error = ref('')
const form = ref({ item: null, warehouse: null, min_qty: '' })
const unitName = computed(() => found.value.find((f) => f.item === form.value.item)?.base_unit)
const qty = (v) => Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 3 })
const columns = [
  { name: 'item', label: 'Товар', field: 'item_name', align: 'left', classes: 'text-weight-medium' },
  { name: 'warehouse', label: 'Склад', field: 'warehouse_name', align: 'left' },
  { name: 'qty', label: 'Остаток', field: (r) => `${qty(r.qty)} ${r.unit}`, align: 'right', classes: 'text-negative' },
  { name: 'min', label: 'Минимум', field: (r) => `${qty(r.min_qty)} ${r.unit}`, align: 'right' },
  { name: 'order', label: 'Не хватает до минимума', field: (r) => `${qty(Number(r.min_qty) - Number(r.qty))} ${r.unit}`, align: 'right' },
]

async function load() {
  const [low, all] = await Promise.all([apiGet('inventory/stock/low/'), apiGet('inventory/min-stock/')])
  rows.value = low.data ?? []
  rules.value = all.data ?? []
}

async function search(text, update, abort) {
  if (text.trim().length < 2) return update(() => (found.value = []))
  const { ok, data } = await apiGet(`inventory/stock/lookup/?search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  const unique = [...new Map(data.map((u) => [u.item, u])).values()]
  update(() => (found.value = unique.map((u) => ({ item: u.item, base_unit: u.base_unit, label: `${u.item_name} (остаток ${Number(u.stock)} ${u.base_unit})` }))))
}

async function save() {
  error.value = ''
  const { ok, data } = await apiPost('inventory/min-stock/', form.value)
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  open.value = false
  form.value = { item: null, warehouse: null, min_qty: '' }
  load()
}

async function remove(rule) {
  const { ok } = await apiDelete(`inventory/min-stock/${rule.id}/`)
  if (ok) load()
}

onMounted(load)
defineExpose({ load })
void props
</script>
