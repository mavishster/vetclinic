<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.md" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 1000px; max-width: 98vw">
      <q-form @submit="save">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ title }}</div>
          <q-btn v-if="form.id" flat no-caps icon="history" label="История цен" @click="openHistory" />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="row q-col-gutter-sm">
            <q-input v-model="form.name" label="Название *" outlined dense autofocus class="col-12 col-md-8" />
            <q-select v-model="form.group" :options="groups" option-value="id" option-label="name" emit-value
              map-options outlined dense label="Группа *" class="col-12 col-md-4" />
            <q-input v-model="form.article" label="Артикул" outlined dense class="col-6 col-md-3" />
            <template v-if="isGoods">
              <q-select v-model="form.base_unit" :options="units" option-value="id" option-label="name" emit-value
                map-options outlined dense label="Единица учёта *" class="col-6 col-md-3"
                hint="В ней хранится остаток на складе" />
              <q-input v-model="form.barcode" label="Штрихкод" outlined dense class="col-6 col-md-3" />
            </template>
            <q-input v-model="form.manual_cost" type="number" step="0.01" min="0" outlined dense clearable
              :label="isGoods ? `Себестоимость за ${baseUnitName || 'ед.'}` : 'Себестоимость'"
              :hint="isGoods ? 'Если склад не ведётся. При учёте — из приходных накладных' : 'Например, цена анализа во внешней лаборатории'"
              class="col-6 col-md-3" />
            <q-input v-model="form.description" label="Описание" type="textarea" autogrow outlined dense class="col-12"
              :hint="isGoods ? '' : 'Что входит в услугу — пригодится администраторам при записи'" />
          </div>
          <div class="row q-gutter-md q-mt-xs">
            <q-checkbox v-model="form.for_sale" label="Продаётся" dense />
            <q-checkbox v-if="!isGoods" v-model="form.is_call" label="Вызов на дом" dense />
            <q-checkbox v-if="form.id" v-model="form.is_active" label="Активен" dense />
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-sm">{{ isGoods ? 'Единицы продажи и закупки, цены' : 'Цена' }}</div>
          <div v-for="(unit, index) in form.units" :key="index" class="unit-row q-pa-sm q-mb-sm">
            <div class="row q-col-gutter-sm items-start">
              <q-select v-if="isGoods" v-model="unit.unit" :options="units" option-value="id" option-label="name"
                emit-value map-options outlined dense label="Единица" class="col-6 col-sm-2" />
              <q-input v-if="isGoods" v-model="unit.ratio" type="number" step="0.001" min="0" outlined dense
                :label="`${baseUnitName || 'баз. ед.'} в одной`" class="col-6 col-sm-2" />
              <div v-if="isGoods" class="col-12 col-sm-2">
                <q-btn-toggle v-model="unit.pricing" no-caps unelevated dense toggle-color="primary" spread
                  :options="[{ label: 'Цена', value: 'fixed' }, { label: 'Наценка', value: 'markup' }]" />
              </div>
              <q-input v-if="unit.pricing === 'fixed'" v-model="unit.price" type="number" step="0.01" min="0" outlined
                dense label="Цена, ₽" class="col-6 col-sm-2" />
              <q-input v-else v-model="unit.markup_percent" type="number" step="0.01" min="0" outlined dense clearable
                label="Наценка, %" :placeholder="groupMarkupHint" stack-label class="col-6 col-sm-2"
                hint="Пусто — как у группы" />
              <q-input v-model="unit.price_min" type="number" step="0.01" min="0" outlined dense clearable
                label="Мин. цена" class="col-6 col-sm-2" />
              <q-input v-model="unit.price_max" type="number" step="0.01" min="0" outlined dense clearable
                label="Макс. цена" class="col-6 col-sm-2" />
            </div>
            <div class="row q-col-gutter-sm items-center q-mt-xs">
              <q-select v-if="isGoods && unit.pricing === 'markup'" v-model="unit.rounding" :options="ROUNDING"
                emit-value map-options outlined dense label="Округлять до" class="col-6 col-sm-2" />
              <q-input v-if="isGoods" v-model="unit.barcode" outlined dense label="Штрихкод единицы" class="col-6 col-sm-3" />
              <div v-if="isGoods" class="col-auto">
                <q-checkbox v-model="unit.for_sale" label="продажа" dense class="q-mr-md" />
                <q-checkbox v-model="unit.for_purchase" label="закупка" dense />
              </div>
              <div v-if="unit.current_price && unit.pricing === 'markup'" class="col-auto text-grey-8">
                сейчас: <b>{{ money(unit.current_price) }}</b>
              </div>
              <q-space />
              <q-btn v-if="isGoods" flat dense round icon="delete" color="grey-7" @click="form.units.splice(index, 1)">
                <q-tooltip>Убрать единицу</q-tooltip>
              </q-btn>
            </div>
          </div>
          <q-btn v-if="isGoods" flat dense no-caps color="primary" icon="add" label="Добавить единицу" @click="addUnit" />
          <div v-if="isGoods" class="text-caption text-grey-7 q-mt-sm">
            Пример: единица учёта — «таб.»; «упак.» = 216 таб. по 600 ₽ и «таб.» = 1 по 3 ₽. Остаток ведётся в таблетках.
            Цена по наценке считается от закупочной цены партии; мин. и макс. цена позволяют менять цену в счёте.
          </div>
        </q-card-section>

        <q-card-section v-if="!isGoods && canSeeUsers" class="q-pt-none">
          <q-select v-model="form.responsible" :options="users" option-value="id" option-label="label" emit-value
            map-options multiple use-chips outlined dense label="Ответственные сотрудники"
            hint="Их будет предлагать счёт при добавлении услуги; первыми — те, кто в смене" />
        </q-card-section>

        <q-card-section v-if="errors.length" class="q-pt-none">
          <div v-for="error in errors" :key="error" class="text-negative">{{ error }}</div>
        </q-card-section>

        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn v-if="canSave" type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>

  <q-dialog v-model="historyOpen">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">История цен</q-card-section>
      <q-list dense separator>
        <q-item v-for="(row, i) in history" :key="i">
          <q-item-section>
            <q-item-label>{{ row.unit }} — {{ row.pricing === 'fixed' ? money(row.price) : `наценка ${row.markup_percent ?? 'как у группы'}${row.markup_percent ? ' %' : ''}` }}</q-item-label>
            <q-item-label caption>{{ new Date(row.date).toLocaleString('ru-RU') }}{{ row.user ? ` · ${row.user}` : '' }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-if="!history.length"><q-item-section class="text-grey-7">Изменений нет</q-item-section></q-item>
      </q-list>
      <q-card-actions align="right"><q-btn flat label="Закрыть" v-close-popup /></q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import { money } from './money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null }, // null — новый
  kind: { type: String, default: 'goods' }, // вид нового: goods | service
})
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()
const ROUNDING = [
  { label: 'копеек', value: '0.01' },
  { label: 'рубля', value: '1.00' },
  { label: '5 ₽', value: '5.00' },
  { label: '10 ₽', value: '10.00' },
]

const form = ref({ units: [] })
const errors = ref([])
const saving = ref(false)
const allGroups = ref([])
const units = ref([])
const users = ref([])
const history = ref([])
const historyOpen = ref(false)
const canSeeUsers = can('core.view_user')

const isGoods = computed(() => form.value.kind === 'goods')
const title = computed(() => (form.value.id ? form.value.name : isGoods.value ? 'Новый товар' : 'Новая услуга'))
const canSave = computed(() => can(form.value.id ? 'catalog.change_item' : 'catalog.add_item'))
const groups = computed(() => allGroups.value.filter((g) => g.kind === form.value.kind))
const baseUnitName = computed(() => units.value.find((u) => u.id === form.value.base_unit)?.name)
const groupMarkupHint = computed(() => {
  const markup = allGroups.value.find((g) => g.id === form.value.group)?.markup_percent
  return markup ? `как у группы: ${Number(markup)}` : 'у группы нет наценки'
})

const newUnit = (unitId, ratio = '1') => ({
  unit: unitId, ratio, pricing: 'fixed', price: null, markup_percent: null, price_min: null, price_max: null,
  rounding: '0.01', barcode: '', for_sale: true, for_purchase: false,
})

function addUnit() {
  form.value.units.push(newUnit(null))
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    errors.value = []
    const [g, u, people] = await Promise.all([
      apiGet('catalog/groups/?active=true'),
      apiGet('catalog/units/?active=true'),
      canSeeUsers ? apiGet('core/users/') : Promise.resolve({ data: [] }),
    ])
    allGroups.value = g.data ?? []
    units.value = u.data ?? []
    users.value = (people.data ?? []).map((p) => ({ id: p.id, label: p.full_name || p.username }))
    if (props.item) {
      form.value = { ...props.item, units: props.item.units.map((x) => ({ ...x })) }
      return
    }
    const serviceUnit = units.value.find((x) => x.name === 'усл.')?.id ?? null
    const pieceUnit = units.value.find((x) => x.name === 'шт.')?.id ?? null
    const goods = props.kind === 'goods'
    form.value = {
      kind: props.kind, name: '', group: null, article: '', description: '', barcode: '', manual_cost: null,
      for_sale: true, is_call: false, is_active: true, responsible: [],
      base_unit: goods ? pieceUnit : serviceUnit,
      units: [newUnit(goods ? pieceUnit : serviceUnit)],
    }
  },
)

// Сменили единицу учёта у нового товара — первая единица продажи тоже она.
watch(
  () => form.value.base_unit,
  (unitId) => {
    if (!form.value.id && form.value.units?.length === 1 && Number(form.value.units[0].ratio) === 1) {
      form.value.units[0].unit = unitId
    }
  },
)

const clean = (value) => (value === '' || value === undefined ? null : value)

async function save() {
  errors.value = []
  const body = {
    kind: form.value.kind, name: form.value.name, group: form.value.group, article: form.value.article,
    description: form.value.description, base_unit: form.value.base_unit, barcode: form.value.barcode || '',
    manual_cost: clean(form.value.manual_cost), for_sale: form.value.for_sale, is_call: form.value.is_call,
    is_active: form.value.is_active,
    units: form.value.units.map((u) => ({
      ...(u.id ? { id: u.id } : {}),
      unit: isGoods.value ? u.unit : form.value.base_unit,
      ratio: u.ratio || '1', pricing: u.pricing, price: clean(u.price), markup_percent: clean(u.markup_percent),
      price_min: clean(u.price_min), price_max: clean(u.price_max), rounding: u.rounding || '0.01',
      barcode: u.barcode || '', for_sale: u.for_sale, for_purchase: u.for_purchase,
    })),
  }
  if (!isGoods.value && canSeeUsers) body.responsible = form.value.responsible
  saving.value = true
  const { ok, data } = form.value.id
    ? await apiPatch(`catalog/items/${form.value.id}/`, body)
    : await apiPost('catalog/items/', body)
  saving.value = false
  if (!ok) {
    errors.value = Object.entries(fieldErrors(data)).map(([field, text]) => (field === 'non_field_errors' ? text : `${field}: ${text}`))
    return
  }
  emit('update:modelValue', false)
  emit('saved', data)
  $q.notify({ type: 'positive', message: 'Сохранено' })
}

async function openHistory() {
  history.value = (await apiGet(`catalog/items/${form.value.id}/price-history/`)).data ?? []
  historyOpen.value = true
}
</script>

<style scoped>
.unit-row {
  border: 1px solid rgba(127, 127, 127, 0.25);
  border-radius: 6px;
}
</style>
