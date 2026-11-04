<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.md" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 900px; max-width: 98vw">
      <q-form @submit="save">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ form.id ? form.name : 'Новая комбинация' }}</div>
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="row q-col-gutter-sm">
            <q-input v-model="form.name" label="Название *" outlined dense autofocus class="col-12 col-md-8" />
            <q-select v-model="form.group" :options="groups" option-value="id" option-label="name" emit-value
              map-options outlined dense label="Группа *" class="col-12 col-md-4" />
          </div>
          <q-btn-toggle v-model="form.is_template" no-caps unelevated toggle-color="primary" class="q-mt-sm"
            :options="[{ label: 'Одной строкой в счёте', value: false }, { label: 'Шаблон: позиции по отдельности', value: true }]" />
          <div class="text-caption text-grey-7 q-mt-xs">
            {{ form.is_template
              ? 'Шаблон просто добавляет все позиции в счёт по отдельности — быстрый способ набрать типовой список.'
              : 'Комбинация попадает в счёт одной строкой со своим составом и ценами позиций.' }}
          </div>
          <q-select v-if="!form.is_template" v-model="form.print_mode" :options="PRINT_MODES" emit-value map-options
            outlined dense label="Как печатать в счёте и чеке" class="q-mt-sm" style="max-width: 420px" />
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-sm">Состав</div>
          <div v-for="(line, index) in form.lines" :key="index" class="row q-col-gutter-sm items-center q-mb-xs">
            <q-select v-model="line.item_unit" :options="line.options" option-value="id" option-label="label" emit-value
              map-options use-input input-debounce="300" outlined dense label="Товар или услуга" class="col-12 col-sm-6"
              @filter="(text, update, abort) => searchUnits(line, text, update, abort)"
              @update:model-value="(id) => onPick(line, id)" />
            <q-input v-model="line.quantity" type="number" step="0.001" min="0" outlined dense label="Кол-во" class="col-4 col-sm-2" />
            <q-input v-model="line.price_override" type="number" step="0.01" min="0" outlined dense clearable
              label="Своя цена" :placeholder="line.current_price ? money(line.current_price) : ''" stack-label
              class="col-5 col-sm-2" />
            <div class="col-2 col-sm-1 text-right text-weight-medium">{{ lineTotal(line) }}</div>
            <div class="col-1"><q-btn flat round dense icon="close" color="grey-7" @click="form.lines.splice(index, 1)" /></div>
          </div>
          <div class="row items-center q-mt-sm">
            <q-btn flat dense no-caps color="primary" icon="add" label="Добавить позицию" @click="addLine" />
            <q-btn flat dense no-caps icon="restart_alt" label="Сбросить свои цены" class="q-ml-md"
              @click="form.lines.forEach((l) => (l.price_override = null))" />
            <q-space />
            <div class="text-subtitle1">Итого: <b>{{ total }}</b></div>
          </div>
          <div class="text-caption text-grey-7 q-mt-xs">
            «Своя цена» пустая — позиция идёт по текущей цене прайса и меняется вместе с ним.
            Заданная — зафиксирована для этой комбинации (например, приём в составе вакцинации бесплатно).
          </div>
        </q-card-section>

        <q-card-section v-if="errors.length" class="q-pt-none">
          <div v-for="error in errors" :key="error" class="text-negative">{{ error }}</div>
        </q-card-section>

        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-if="item?.id && can('catalog.delete_item')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
          <q-space />
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn v-if="canSave" type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { deleteItem } from './deleteItem'
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { money } from './money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()

// Удалить — только если позиция нигде не использовалась; иначе — предложим сделать неактивной.
async function remove() {
  const result = await deleteItem($q, props.item)
  if (!result) return
  $q.notify({ type: 'positive', message: result === 'deleted' ? 'Позиция удалена' : 'Позиция стала неактивной' })
  emit('saved', null)
  emit('update:modelValue', false)
}
const PRINT_MODES = [
  { value: 'full', label: 'Все позиции с ценами' },
  { value: 'name', label: 'Только название комбинации' },
  { value: 'services', label: 'Название и услуги с ценами' },
  { value: 'composition', label: 'Название и состав без цен' },
]
const form = ref({ lines: [] })
const groups = ref([])
const errors = ref([])
const saving = ref(false)
const canSave = computed(() => can(form.value.id ? 'catalog.change_item' : 'catalog.add_item'))

const unitPrice = (line) => (line.price_override !== null && line.price_override !== '' ? Number(line.price_override) : line.current_price === null ? null : Number(line.current_price))
function lineTotal(line) {
  const price = unitPrice(line)
  return price === null || !line.item_unit ? '' : money(price * Number(line.quantity || 0))
}
const total = computed(() => {
  const prices = form.value.lines.filter((l) => l.item_unit).map((l) => unitPrice(l) === null ? null : unitPrice(l) * Number(l.quantity || 0))
  return prices.includes(null) ? 'по закупке' : money(prices.reduce((a, b) => a + b, 0))
})

const addLine = () => form.value.lines.push({ item_unit: null, quantity: '1', price_override: null, current_price: null, options: [] })

// Поиск позиции: по товарам и услугам, каждая единица продажи — отдельный вариант.
async function searchUnits(line, text, update, abort) {
  if (text.trim().length < 2) return update(() => {})
  const { ok, data } = await apiGet(`catalog/items/?kind=goods,service&active=true&page_size=20&search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => {
    line.options = data.results.flatMap((item) =>
      item.units.filter((u) => u.for_sale).map((u) => ({
        id: u.id, label: `${item.name} — ${u.unit_name}${u.current_price ? ` (${money(u.current_price)})` : ''}`,
        price: u.current_price,
      })),
    )
  })
}

function onPick(line, id) {
  line.current_price = line.options.find((o) => o.id === id)?.price ?? null
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    errors.value = []
    groups.value = ((await apiGet('catalog/groups/?active=true&kind=service')).data ?? [])
    if (props.item) {
      form.value = {
        ...props.item,
        lines: props.item.lines.map((l) => ({
          ...l,
          options: [{ id: l.item_unit, label: `${l.item_name} — ${l.unit_name}`, price: l.current_price }],
        })),
      }
    } else {
      form.value = { kind: 'combo', name: '', group: null, is_template: false, print_mode: 'full', lines: [] }
      addLine()
    }
  },
)

async function save() {
  errors.value = []
  const body = {
    kind: 'combo', name: form.value.name, group: form.value.group, is_template: form.value.is_template,
    print_mode: form.value.print_mode,
    lines: form.value.lines.filter((l) => l.item_unit).map((l) => ({
      item_unit: l.item_unit, quantity: l.quantity || '1',
      price_override: l.price_override === '' ? null : l.price_override,
    })),
  }
  saving.value = true
  const { ok, data } = form.value.id
    ? await apiPatch(`catalog/items/${form.value.id}/`, body)
    : await apiPost('catalog/items/', body)
  saving.value = false
  if (!ok) {
    errors.value = Object.values(fieldErrors(data))
    return
  }
  emit('update:modelValue', false)
  emit('saved', data)
  $q.notify({ type: 'positive', message: 'Комбинация сохранена' })
}
</script>
