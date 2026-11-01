<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Шаблоны медкарты</h1>
      <q-btn color="primary" unelevated icon="add" label="Новый шаблон" @click="open()" />
    </div>
    <p class="text-grey-8">
      Готовый текст для вкладок медкарты. В тексте можно использовать переменные — они подставятся из записи — и поля
      для заполнения <code>[___]</code> (или <code>[___ подсказка]</code>): врач переходит между ними клавишей Tab.
      Личные шаблоны видит только автор.
    </p>
    <q-table :rows="rows" :columns="columns" row-key="id" flat bordered :pagination="{ rowsPerPage: 50 }"
      no-data-label="Шаблонов нет" rows-per-page-label="Строк на странице" @row-click="(e, row) => open(row)">
      <template #body-cell-name="props">
        <q-td :props="props">{{ props.row.name }}
          <q-badge v-if="props.row.is_personal" color="primary" outline label="личный" class="q-ml-xs" />
          <q-badge v-if="!props.row.is_active" color="grey-6" label="неактивен" class="q-ml-xs" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="editorOpen">
      <q-card style="width: 820px; max-width: 96vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ form.id ? 'Шаблон' : 'Новый шаблон' }}</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.name" outlined dense label="Название *" class="col-12 col-sm-6" />
              <q-select v-model="form.section" :options="SECTIONS" emit-value map-options outlined dense label="Вкладка" class="col-6 col-sm-3" />
              <q-select v-model="form.purpose" :options="purposes" option-value="id" option-label="name" emit-value map-options
                outlined dense clearable label="Цель обращения" class="col-6 col-sm-3" />
            </div>
            <q-editor v-model="form.body_html" min-height="220px"
              :toolbar="[['bold', 'italic', 'underline'], ['unordered', 'ordered'], ['undo', 'redo']]" />
            <div class="text-caption">
              Переменные (нажмите, чтобы добавить в конец):
              <q-chip v-for="v in variables" :key="v.name" dense clickable size="sm" @click="form.body_html += ` ${v.name}`">
                {{ v.name }}<q-tooltip>{{ v.title }}</q-tooltip>
              </q-chip>
              <q-chip dense clickable size="sm" color="amber-2" text-color="dark" @click="form.body_html += ' [___]'">[___] поле</q-chip>
            </div>
            <div class="row q-gutter-md">
              <q-checkbox v-model="form.personal" label="Личный — вижу только я" dense />
              <q-checkbox v-model="form.is_active" label="Активен" dense />
            </div>
            <div v-if="error" class="text-negative">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-if="form.id" flat color="negative" label="Удалить" @click="remove" />
            <q-space />
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn type="submit" color="primary" unelevated label="Сохранить" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
// Шаблоны текста медкарты: общие и личные, с переменными и полями для заполнения.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, fieldErrors } from '@/api'

const $q = useQuasar()
const SECTIONS = [
  { value: 'treatment', label: 'Описание лечения' }, { value: 'recommendations', label: 'Рекомендации' }, { value: 'both', label: 'Обе вкладки' },
]
const rows = ref([])
const purposes = ref([])
const variables = ref([])
const editorOpen = ref(false)
const form = ref({})
const error = ref('')
const columns = [
  { name: 'name', label: 'Название', field: 'name', align: 'left', classes: 'text-weight-medium' },
  { name: 'section', label: 'Вкладка', field: (r) => SECTIONS.find((s) => s.value === r.section)?.label, align: 'left' },
  { name: 'purpose', label: 'Цель обращения', field: 'purpose_name', align: 'left' },
]

async function load() {
  rows.value = (await apiGet('medical/text-templates/')).data ?? []
}

function open(row = null) {
  error.value = ''
  form.value = row
    ? { ...row, personal: row.is_personal }
    : { name: '', section: 'treatment', purpose: null, body_html: '', personal: false, is_active: true }
  editorOpen.value = true
}

async function save() {
  error.value = ''
  const body = { name: form.value.name, section: form.value.section, purpose: form.value.purpose, body_html: form.value.body_html,
    personal: form.value.personal, is_active: form.value.is_active }
  const { ok, data } = form.value.id
    ? await apiPatch(`medical/text-templates/${form.value.id}/`, body)
    : await apiPost('medical/text-templates/', body)
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  editorOpen.value = false
  load()
}

function remove() {
  $q.dialog({ title: 'Удалить шаблон?', message: form.value.name, cancel: { label: 'Отмена', flat: true }, ok: { label: 'Удалить', color: 'negative', unelevated: true } })
    .onOk(async () => {
      await apiDelete(`medical/text-templates/${form.value.id}/`)
      editorOpen.value = false
      load()
    })
}

onMounted(async () => {
  const [p, v] = await Promise.all([apiGet('scheduling/purposes/?active=true'), apiGet('medical/text-templates/variables/')])
  purposes.value = p.data ?? []
  variables.value = v.data ?? []
  load()
})
</script>
