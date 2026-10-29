<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">{{ title }}</h1>
      <q-btn v-if="canAdd" color="primary" icon="add" label="Добавить" unelevated @click="openEditor()" />
    </div>

    <div class="row q-col-gutter-sm q-mb-md">
      <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Поиск"
        class="col-12 col-sm-5" @update:model-value="load">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-select v-for="field in selectFields" :key="field.name" v-model="filters[field.name]"
        :options="options[field.name]" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable :label="field.label" class="col-12 col-sm-3"
        @update:model-value="load" />
      <q-btn-toggle v-model="active" :options="activeOptions" no-caps unelevated toggle-color="primary"
        class="col-auto" @update:model-value="load" />
    </div>

    <q-table :rows="rows" :columns="columns" row-key="id" :loading="loading" flat bordered
      :pagination="{ rowsPerPage: 50 }" no-data-label="Записей нет" rows-per-page-label="Строк на странице">
      <template #body-cell-name="props">
        <q-td :props="props" :class="{ 'text-grey-6': !props.row.is_active }">
          {{ props.row.name }}
          <q-badge v-if="!props.row.is_active" color="grey-6" label="неактивна" class="q-ml-sm" />
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn v-if="canChange" flat round dense icon="edit" @click="openEditor(props.row)">
            <q-tooltip>Изменить</q-tooltip>
          </q-btn>
          <q-btn v-if="canChange" flat round dense :icon="props.row.is_active ? 'block' : 'check_circle'"
            @click="toggleActive(props.row)">
            <q-tooltip>{{ props.row.is_active ? 'Деактивировать' : 'Активировать' }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canDelete" flat round dense icon="delete" color="negative" @click="remove(props.row)">
            <q-tooltip>Удалить</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="editorOpen">
      <q-card style="width: 420px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ editing.id ? 'Изменить' : 'Добавить' }}</q-card-section>
          <q-card-section class="q-gutter-md">
            <q-input v-model="editing.name" label="Название" outlined autofocus
              :error="!!errors.name" :error-message="errors.name" />
            <q-select v-for="field in selectFields" :key="field.name" v-model="editing[field.name]"
              :options="options[field.name]" option-value="id" option-label="name" emit-value map-options
              outlined :label="field.label" :error="!!errors[field.name]" :error-message="errors[field.name]" />
            <div v-if="errors.non_field_errors" class="text-negative">{{ errors.non_field_errors }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn type="submit" color="primary" label="Сохранить" unelevated :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
// Общий экран справочника (DRY): список, поиск, фильтры, добавление, изменение,
// деактивация, удаление. Справочник описывается несколькими параметрами:
//   endpoint — адрес API, permission — «модуль.модель» для проверки прав,
//   fields — дополнительные поля-списки, например вид у породы.
import { computed, onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({
  title: { type: String, required: true },
  endpoint: { type: String, required: true }, // 'clients/species/'
  permission: { type: String, required: true }, // 'clients.species'
  fields: { type: Array, default: () => [] }, // [{ name, label, endpoint }]
})

const $q = useQuasar()
const [app, model] = props.permission.split('.')
const canAdd = computed(() => can(`${app}.add_${model}`))
const canChange = computed(() => can(`${app}.change_${model}`))
const canDelete = computed(() => can(`${app}.delete_${model}`))

const selectFields = props.fields
const rows = ref([])
const loading = ref(false)
const search = ref('')
const active = ref('true')
const filters = reactive({})
const options = reactive({})
const activeOptions = [
  { label: 'Активные', value: 'true' },
  { label: 'Неактивные', value: 'false' },
  { label: 'Все', value: 'all' },
]

const optionName = (field, id) => options[field.name]?.find((o) => o.id === id)?.name ?? ''
const columns = [
  { name: 'name', label: 'Название', field: 'name', align: 'left', sortable: true },
  ...selectFields.map((field) => ({
    name: field.name,
    label: field.label,
    align: 'left',
    sortable: true,
    field: (row) => optionName(field, row[field.name]),
  })),
  { name: 'actions', label: '', field: 'id', align: 'right' },
]

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (search.value) params.set('search', search.value)
  if (active.value !== 'all') params.set('active', active.value)
  for (const field of selectFields) if (filters[field.name]) params.set(field.name, filters[field.name])
  const { ok, data } = await apiGet(`${props.endpoint}?${params}`)
  rows.value = ok ? data : []
  loading.value = false
  if (!ok) $q.notify({ type: 'negative', message: 'Не удалось загрузить список' })
}

async function loadOptions() {
  for (const field of selectFields) {
    const { ok, data } = await apiGet(`${field.endpoint}?active=true`)
    options[field.name] = ok ? data : []
  }
}

const editorOpen = ref(false)
const editing = ref({})
const errors = ref({})
const saving = ref(false)

function openEditor(row = null) {
  errors.value = {}
  editing.value = row ? { ...row } : Object.fromEntries(selectFields.map((f) => [f.name, filters[f.name] ?? null]))
  editorOpen.value = true
}

async function save() {
  saving.value = true
  const body = { name: editing.value.name }
  for (const field of selectFields) body[field.name] = editing.value[field.name]
  const { ok, data } = editing.value.id
    ? await apiPatch(`${props.endpoint}${editing.value.id}/`, body)
    : await apiPost(props.endpoint, body)
  saving.value = false
  if (!ok) {
    errors.value = fieldErrors(data)
    return
  }
  editorOpen.value = false
  $q.notify({ type: 'positive', message: 'Сохранено' })
  load()
}

async function toggleActive(row) {
  const { ok } = await apiPatch(`${props.endpoint}${row.id}/`, { is_active: !row.is_active })
  if (ok) load()
  else $q.notify({ type: 'negative', message: 'Не удалось изменить запись' })
}

function remove(row) {
  $q.dialog({
    title: 'Удалить запись?',
    message: `«${row.name}» исчезнет из справочника. Если запись уже используется, лучше деактивировать её.`,
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
    persistent: true,
  }).onOk(async () => {
    const { ok } = await apiDelete(`${props.endpoint}${row.id}/`)
    if (ok) load()
    else $q.notify({ type: 'negative', message: 'Не удалось удалить запись' })
  })
}

onMounted(async () => {
  await loadOptions()
  load()
})
</script>
