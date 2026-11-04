<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.md" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 1000px; max-width: 98vw">
      <q-form @submit="save">
        <q-card-section class="row items-center">
          <div class="text-h6 col">{{ title }}</div>
          <template v-if="form.id">
            <q-btn v-if="isGoods" flat no-caps icon="qr_code_2" label="Этикетки" @click="labelsOpen = true" />
            <q-btn flat no-caps icon="layers" label="В комбинациях" @click="openCombos" />
            <q-btn v-if="isGoods" flat no-caps icon="unpublished" label="Убранные единицы" @click="openRemoved" />
            <q-btn flat no-caps icon="history" label="История цен" @click="openHistory" />
          </template>
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="row q-col-gutter-sm">
            <q-input v-model="form.name" label="Название *" outlined dense autofocus class="col-12 col-md-8" />
            <q-select v-model="form.group" :options="groups" option-value="id" option-label="name" emit-value
              map-options outlined dense use-input input-debounce="0" new-value-mode="add-unique" label="Группа *"
              class="col-12 col-md-4" hint="Нет в списке — впишите и нажмите Enter" @new-value="addGroup" />
            <q-input v-model="form.article" label="Артикул" outlined dense class="col-6 col-md-3" />
            <template v-if="isGoods">
              <q-select v-model="form.base_unit" :options="units" option-value="id" option-label="name" emit-value
                map-options outlined dense use-input input-debounce="0" new-value-mode="add-unique"
                label="Единица учёта *" class="col-6 col-md-3" hint="В ней хранится остаток на складе"
                @new-value="createUnit" />
              <q-input v-model="form.barcode" label="Штрихкод" outlined dense class="col-6 col-md-3" />
            </template>
            <div v-if="can('catalog.view_cost')" class="col-6 col-md-3 row no-wrap q-gutter-x-xs">
              <q-input v-model="costInUnit" type="number" step="0.01" min="0" outlined dense clearable class="col"
                :label="isGoods ? 'Себестоимость' : 'Себестоимость'"
                :hint="costHint" />
              <q-select v-if="isGoods && costUnits.length > 1" v-model="costUnitId" :options="costUnits" option-value="unit"
                option-label="name" emit-value map-options outlined dense style="min-width: 90px" label="за" />
            </div>
            <q-select v-model="form.prevention_kind" :options="PREVENTION_KINDS" option-value="id" option-label="name"
              emit-value map-options outlined dense label="Профилактика" class="col-12 col-md-4"
              hint="Отметите в медкарте — система предложит записать процедуру" />
            <q-input v-model="form.description" label="Описание" type="textarea" autogrow outlined dense class="col-12"
              :hint="isGoods ? '' : 'Что входит в услугу — пригодится администраторам при записи'" />
          </div>
          <div class="row q-gutter-md q-mt-xs">
            <q-checkbox v-model="form.for_sale" label="Продаётся" dense />
            <q-checkbox v-model="form.combo_only" label="Только для комбинаций" dense>
              <q-tooltip>Отдельно в счёт не добавляется — только в составе комбинаций</q-tooltip>
            </q-checkbox>
            <q-checkbox v-if="!isGoods" v-model="form.is_call" label="Вызов на дом" dense />
            <q-checkbox v-if="form.id" v-model="form.is_active" label="Активен" dense />
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-sm">{{ isGoods ? 'Единицы продажи и закупки, цены' : 'Цена' }}</div>
          <div v-for="(unit, index) in form.units" :key="index" class="unit-row q-pa-sm q-mb-sm">
            <div class="row q-col-gutter-sm items-start">
              <q-select v-if="isGoods" v-model="unit.unit" :options="units" option-value="id" option-label="name"
                emit-value map-options outlined dense use-input input-debounce="0" new-value-mode="add-unique"
                label="Единица" class="col-6 col-sm-2" @new-value="createUnit" />
              <q-input v-if="isGoods" v-model="unit.ratio" type="number" step="0.001" min="0" outlined dense
                :label="`${baseUnitName || 'баз. ед.'} в одной`" class="col-6 col-sm-2" />
              <div v-if="isGoods" class="col-12 col-sm-2">
                <q-btn-toggle v-model="unit.pricing" no-caps unelevated dense toggle-color="primary" spread
                  :options="[{ label: 'Цена', value: 'fixed' }, { label: 'Наценка', value: 'markup' }]" />
              </div>
              <q-input v-if="unit.pricing === 'fixed'" v-model="unit.price" type="number" step="0.01" min="0" outlined
                dense :label="`Цена, ${currency()}`" class="col-6 col-sm-2" />
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
              <div v-if="isGoods && unitSummary(unit)" class="col-auto text-caption"
                :class="unitSummary(unit).wrong ? 'text-negative' : 'text-grey-7'">
                {{ unitSummary(unit).text }}
              </div>
              <q-space />
              <q-btn v-if="isGoods" flat dense round icon="delete" color="grey-7" @click="form.units.splice(index, 1)">
                <q-tooltip>Убрать единицу</q-tooltip>
              </q-btn>
            </div>
          </div>
          <q-btn v-if="isGoods" flat dense no-caps color="primary" icon="add" label="Добавить единицу" @click="addUnit" />
          <div v-if="isGoods" class="text-caption text-grey-7 q-mt-sm">
            Пример: единица учёта — «таб.»; «упак.» = 216 таб. по 600 {{ currency() }} и «таб.» = 1 по 3 {{ currency() }}. Остаток ведётся в таблетках.
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
          <q-btn v-if="item?.id && can('catalog.delete_item')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
          <q-space />
          <q-btn flat label="Отмена" v-close-popup />
          <q-btn v-if="canSave" type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>

  <q-dialog v-model="labelsOpen">
    <q-card style="width: 420px; max-width: 95vw">
      <q-card-section class="text-h6">Этикетки</q-card-section>
      <q-card-section class="q-pt-none q-gutter-y-sm">
        <div v-for="unit in form.units.filter((u) => u.id)" :key="unit.id" class="row items-center q-gutter-x-sm">
          <div class="col">{{ units.find((x) => x.id === unit.unit)?.name }}<span v-if="unit.barcode" class="text-grey-7"> · {{ unit.barcode }}</span></div>
          <q-input v-model.number="copies[unit.id]" type="number" min="0" dense outlined style="width: 90px" label="Копий" />
        </div>
        <div class="text-caption text-grey-7">Если у единицы нет штрихкода, система присвоит внутренний (начинается с «20») — сканер его узнает.</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn color="primary" unelevated icon="print" label="Печать" @click="printLabels" />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="infoOpen">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">{{ info.title }}</q-card-section>
      <q-list dense separator>
        <q-item v-for="(row, i) in info.rows" :key="i"><q-item-section>{{ row }}</q-item-section></q-item>
        <q-item v-if="!info.rows.length"><q-item-section class="text-grey-7">{{ info.empty }}</q-item-section></q-item>
      </q-list>
      <q-card-actions align="right"><q-btn flat label="Закрыть" v-close-popup /></q-card-actions>
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
import { deleteItem } from './deleteItem'
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, existingByName, fieldErrors, openPostedFile } from '@/api'
import { can } from '@/session'
import { currency, money } from './money'
import { PREVENTION_KINDS } from './routes'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null }, // null — новый
  kind: { type: String, default: 'goods' }, // вид нового: goods | service
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
const ROUNDING = [
  { label: 'копеек', value: '0.01' },
  { label: 'рубля', value: '1.00' },
  { label: `5 ${currency()}`, value: '5.00' },
  { label: `10 ${currency()}`, value: '10.00' },
]

const form = ref({ units: [] })
const errors = ref([])
const saving = ref(false)
const allGroups = ref([])
const units = ref([])
const users = ref([])
const history = ref([])
const historyOpen = ref(false)
const infoOpen = ref(false)
const labelsOpen = ref(false)
const copies = ref({})

async function printLabels() {
  const lines = Object.entries(copies.value).filter(([, n]) => Number(n) > 0).map(([id, n]) => ({ item_unit: id, copies: Number(n) }))
  if (!lines.length) return $q.notify({ type: 'warning', message: 'Укажите, сколько этикеток напечатать' })
  const { ok, data } = await openPostedFile('inventory/labels/', { lines })
  if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data || {}))[0] || 'Не удалось напечатать' })
  labelsOpen.value = false
}
const info = ref({ title: '', rows: [], empty: '' })
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

// Расшифровка строки: «1 упак. = 5 фл. · 700 сом за фл.» — сразу видно, что получается.
function unitSummary(unit) {
  const name = units.value.find((u) => u.id === unit.unit)?.name
  const base = baseUnitName.value
  const ratio = Number(unit.ratio)
  if (!name || !base || !ratio) return null
  if (unit.unit === form.value.base_unit && ratio !== 1) {
    return { wrong: true, text: `«${base}» — единица учёта, в ней всегда 1 ${base}. Для упаковки выберите «упак.»` }
  }
  if (ratio === 1 && unit.unit !== form.value.base_unit) {
    // «таб.» = 1 «упак.» — система не сохранит: продажа 1 таб. списывала бы целую упаковку.
    return { wrong: true, text: `1 ${name} не может равняться 1 ${base}. Если в ${base} несколько ${name}, укажите долю (при 8 ${name} — 0,125)` }
  }
  const perBase = unit.pricing === 'fixed' && Number(unit.price) && ratio !== 1 ? ` · ${money(Number(unit.price) / ratio)} за ${base}` : ''
  return { wrong: false, text: ratio === 1 && unit.unit === form.value.base_unit ? `1 ${base} — единица учёта` : `1 ${name} = ${ratio} ${base}${perBase}` }
}

// Себестоимость хранится за единицу учёта (флакон), а вводить её можно за любую
// единицу товара — например, за упаковку, как в документах поставщика.
const costUnitId = ref(null)
const costUnits = computed(() => {
  const base = { unit: form.value.base_unit, name: baseUnitName.value, ratio: 1 }
  const others = (form.value.units || [])
    .filter((u) => u.unit && u.unit !== form.value.base_unit && Number(u.ratio) > 0)
    .map((u) => ({ unit: u.unit, name: units.value.find((x) => x.id === u.unit)?.name, ratio: Number(u.ratio) }))
  return base.name ? [base, ...others] : others
})
const costRatio = computed(() => costUnits.value.find((u) => u.unit === costUnitId.value)?.ratio || 1)
const costInUnit = computed({
  get: () => {
    if (form.value.manual_cost === null || form.value.manual_cost === undefined || form.value.manual_cost === '') return null
    return Number((Number(form.value.manual_cost) * costRatio.value).toFixed(2))
  },
  set: (value) => {
    form.value.manual_cost = value === null || value === '' ? null : (Number(value) / costRatio.value).toFixed(2)
  },
})
watch(costUnits, (list) => {
  if (!list.some((u) => u.unit === costUnitId.value)) costUnitId.value = form.value.base_unit
})
const costHint = computed(() => {
  if (!isGoods.value) return 'Например, цена анализа во внешней лаборатории'
  const perBase = form.value.manual_cost ? ` = ${money(form.value.manual_cost)} за ${baseUnitName.value}` : ''
  return costRatio.value !== 1 ? `Если склад не ведётся${perBase}` : 'Если склад не ведётся. При учёте — из приходных накладных'
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
      const purchase = form.value.units.find((u) => u.for_purchase && Number(u.ratio) > 1)
      costUnitId.value = purchase ? purchase.unit : form.value.base_unit
      return
    }
    const serviceUnit = units.value.find((x) => x.name === 'усл.')?.id ?? null
    const pieceUnit = units.value.find((x) => x.name === 'шт.')?.id ?? null
    const goods = props.kind === 'goods'
    form.value = {
      kind: props.kind, name: '', group: null, article: '', description: '', barcode: '', manual_cost: null,
      for_sale: true, combo_only: false, is_call: false, is_active: true, responsible: [], prevention_kind: '',
      base_unit: goods ? pieceUnit : serviceUnit,
      units: [newUnit(goods ? pieceUnit : serviceUnit)],
    }
    costUnitId.value = form.value.base_unit
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
    is_active: form.value.is_active, prevention_kind: form.value.prevention_kind || '', combo_only: form.value.combo_only,
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

// Новую группу и единицу можно добавить прямо из карточки — как «+» в VetManager.
async function addGroup(name, done) {
  const existing = existingByName(groups.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('catalog/groups/', { name, kind: form.value.kind === 'service' ? 'service' : 'goods' })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить группу' })
  allGroups.value = [...allGroups.value, data]
  done(data.id, 'add-unique')
}

async function createUnit(name, done) {
  const existing = existingByName(units.value, name)
  if (existing) return done(existing.id, 'add-unique')
  const { ok, data } = await apiPost('catalog/units/', { name })
  if (!ok) return $q.notify({ type: 'negative', message: fieldErrors(data).name || 'Не удалось добавить единицу' })
  units.value = [...units.value, data]
  done(data.id, 'add-unique')
}

async function openCombos() {
  const rows = (await apiGet(`catalog/items/${form.value.id}/combinations/`)).data ?? []
  info.value = { title: 'Входит в комбинации', rows: rows.map((r) => r.name), empty: 'Ни в одной комбинации нет' }
  infoOpen.value = true
}

async function openRemoved() {
  const rows = (await apiGet(`catalog/items/${form.value.id}/removed-units/`)).data ?? []
  info.value = {
    title: 'Убранные единицы',
    rows: rows.map((r) => `${r.unit_name} (${Number(r.ratio)}) — ${r.pricing === 'fixed' ? money(r.price) : `наценка ${r.markup_percent ?? 'как у группы'}`} · убрана ${new Date(r.removed_at).toLocaleDateString('ru-RU')}`),
    empty: 'Убранных единиц нет',
  }
  infoOpen.value = true
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
