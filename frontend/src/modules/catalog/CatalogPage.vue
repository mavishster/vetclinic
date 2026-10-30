<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Товары и услуги</h1>
      <q-btn v-if="can('catalog.add_item') && can('catalog.change_item')" flat color="primary" icon="upload_file"
        label="Импорт из Excel" @click="importOpen = true" />
      <template v-if="can('catalog.add_item')">
        <q-btn outline color="primary" icon="layers" label="Новая комбинация" @click="createCombo" />
        <q-btn outline color="primary" icon="medical_services" label="Новая услуга" @click="create('service')" />
        <q-btn color="primary" unelevated icon="add_box" label="Новый товар" @click="create('goods')" />
      </template>
    </div>

    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" autofocus
        placeholder="Название, артикул или штрихкод" class="col-12 col-md-4" @update:model-value="reload">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn-toggle v-model="kind" no-caps unelevated toggle-color="primary" class="col-auto"
        :options="[{ label: 'Все', value: '' }, { label: 'Товары', value: 'goods' }, { label: 'Услуги', value: 'service' }, { label: 'Комбинации', value: 'combo' }]"
        @update:model-value="onKind" />
      <q-select v-model="group" :options="groupOptions" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Группа" class="col-6 col-md-3" @update:model-value="reload" />
      <q-select v-model="tracked" :options="TRACKED" emit-value map-options dense outlined clearable label="Складской учёт"
        class="col-6 col-md-2" @update:model-value="reload" />
      <q-checkbox v-model="notForSale" label="Не для продажи" dense class="col-auto" @update:model-value="reload" />
      <q-checkbox v-model="showInactive" label="Показать неактивные" dense class="col-auto" @update:model-value="reload" />
    </div>

    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading"
      flat bordered :rows-per-page-options="[25, 50, 100]" no-data-label="Ничего не найдено"
      rows-per-page-label="Строк на странице" @request="onRequest" @row-click="(e, row) => edit(row)">
      <template #body-cell-name="props">
        <q-td :props="props" :class="{ 'text-grey-6': !props.row.is_active }">
          <q-icon :name="KIND_ICONS[props.row.kind]" color="primary"
            size="18px" class="q-mr-sm" />
          <span class="text-weight-medium">{{ props.row.name }}</span>
          <q-badge v-if="!props.row.is_active" color="grey-6" label="неактивен" class="q-ml-sm" />
        </q-td>
      </template>
      <template #body-cell-prices="props">
        <q-td :props="props">
          <span v-if="props.row.kind === 'combo'">
            <b>{{ props.row.combo_price ? money(props.row.combo_price) : 'по закупке' }}</b>
            <span class="text-grey-7"> · {{ props.row.lines.length }} поз.{{ props.row.is_template ? ', шаблон' : '' }}</span>
          </span>
          <span v-for="unit in props.row.units.filter((u) => u.for_sale)" :key="unit.id" class="q-mr-md text-no-wrap">
            {{ unit.unit_name }} — <b>{{ unit.current_price ? money(unit.current_price) : 'по закупке' }}</b>
          </span>
        </q-td>
      </template>
    </q-table>

    <ItemEditDialog v-model="editorOpen" :item="editing" :kind="newKind" @saved="reload" />
    <ComboEditDialog v-model="comboOpen" :item="editing" @saved="reload" />
    <ImportDialog v-model="importOpen" @imported="reload" />
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import ComboEditDialog from './ComboEditDialog.vue'
import ImportDialog from './ImportDialog.vue'
import ItemEditDialog from './ItemEditDialog.vue'
import { money } from './money'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const kind = ref('')
const group = ref(null)
const showInactive = ref(false)
const tracked = ref(null)
const notForSale = ref(false)
const TRACKED = [{ label: 'Товары с учётом', value: 'yes' }, { label: 'Товары без учёта', value: 'no' }]
const groups = ref([])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const editorOpen = ref(false)
const editing = ref(null)
const newKind = ref('goods')
const comboOpen = ref(false)
const importOpen = ref(false)
const KIND_ICONS = { goods: 'inventory_2', service: 'medical_services', combo: 'layers' }

const groupOptions = computed(() => {
  const groupKind = kind.value === 'combo' ? 'service' : kind.value
  return groups.value.filter((g) => !groupKind || g.kind === groupKind)
})
const columns = [
  { name: 'name', label: 'Название', field: 'name', align: 'left' },
  { name: 'group', label: 'Группа', field: 'group_name', align: 'left' },
  { name: 'prices', label: 'Цены', field: 'id', align: 'left' },
  { name: 'article', label: 'Артикул', field: 'article', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  if (search.value) params.set('search', search.value)
  if (kind.value) params.set('kind', kind.value)
  if (group.value) params.set('group', group.value)
  if (!showInactive.value) params.set('active', 'true')
  if (tracked.value) params.set('tracked', tracked.value)
  if (notForSale.value) params.set('not_for_sale', 'true')
  const { ok, data } = await apiGet(`catalog/items/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}

const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
function onKind() {
  group.value = null
  reload()
}
function create(itemKind) {
  editing.value = null
  newKind.value = itemKind
  editorOpen.value = true
}
function createCombo() {
  editing.value = null
  comboOpen.value = true
}
function edit(item) {
  editing.value = item
  if (item.kind === 'combo') comboOpen.value = true
  else editorOpen.value = true
}

onMounted(async () => {
  groups.value = (await apiGet('catalog/groups/?active=true')).data ?? []
  reload()
})
</script>
