<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.md" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 900px; max-width: 98vw">
      <q-card-section class="row items-center">
        <div class="text-h6 col">Импорт прайса из Excel</div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section class="q-pt-none text-body2">
        Подойдёт файл Excel (.xlsx) или CSV с колонками «Название», «Группа», «Цена» и, по желанию, «Вид»
        (товар / услуга), «Единица», «Наценка, %», «Себестоимость», «Артикул», «Штрихкод».
        Колонки узнаются по заголовкам, порядок не важен. Товар ищется по артикулу, а если его нет — по названию:
        найденный обновляется, новый — создаётся. Сначала файл проверяется, и ничего не меняется.
        <div class="q-mt-sm"><a href="/api/catalog/import/template/" class="text-primary">Скачать шаблон</a></div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <div class="row q-col-gutter-sm items-center">
          <q-file v-model="file" outlined dense accept=".xlsx,.csv" label="Файл прайса" class="col-12 col-sm"
            @update:model-value="result = null">
            <template #prepend><q-icon name="table_view" /></template>
          </q-file>
          <div class="col-auto">
            <q-btn outline color="primary" icon="fact_check" label="Проверить" :disable="!file" :loading="busy === 'preview'"
              @click="run('preview')" />
          </div>
        </div>
        <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>

      <q-card-section v-if="result" class="q-pt-none">
        <div class="row q-gutter-sm q-mb-sm">
          <q-chip color="positive" text-color="white" :label="`${done ? 'создано' : 'будет создано'}: ${result.created}`" />
          <q-chip color="primary" text-color="white" :label="`${done ? 'обновлено' : 'будет обновлено'}: ${result.updated}`" />
          <q-chip color="grey-6" text-color="white" :label="`без изменений: ${result.unchanged}`" />
          <q-chip :color="result.errors ? 'negative' : 'grey-5'" text-color="white" :label="`с ошибками: ${result.errors}`" />
        </div>
        <q-table :rows="result.rows" :columns="columns" row-key="line" flat bordered dense
          :pagination="{ rowsPerPage: 20 }" rows-per-page-label="Строк на странице">
          <template #body-cell-action="props">
            <q-td :props="props">
              <q-badge :color="ACTIONS[props.row.action].color" :label="ACTIONS[props.row.action].label" />
              <span v-if="props.row.error" class="text-negative q-ml-sm">{{ props.row.error }}</span>
            </q-td>
          </template>
        </q-table>
        <div v-if="result.total > result.rows.length" class="text-caption text-grey-7 q-mt-xs">
          Показаны первые {{ result.rows.length }} строк из {{ result.total }}.
        </div>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn flat :label="done ? 'Закрыть' : 'Отмена'" v-close-popup />
        <q-btn v-if="result && !done" color="primary" unelevated icon="upload" :loading="busy === 'commit'"
          :disable="!result.created && !result.updated" :label="`Загрузить (${result.created + result.updated})`"
          @click="run('commit')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { apiUpload, fieldErrors } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'imported'])
const ACTIONS = {
  create: { label: 'новый', color: 'positive' },
  update: { label: 'обновится', color: 'primary' },
  unchanged: { label: 'без изменений', color: 'grey-6' },
  error: { label: 'ошибка', color: 'negative' },
}
const columns = [
  { name: 'line', label: 'Строка', field: 'line', align: 'left' },
  { name: 'name', label: 'Название', field: 'name', align: 'left' },
  { name: 'group', label: 'Группа', field: 'group', align: 'left' },
  { name: 'unit', label: 'Ед.', field: 'unit', align: 'left' },
  { name: 'price', label: 'Цена', field: 'price', align: 'right' },
  { name: 'action', label: '', field: 'action', align: 'left' },
]
const file = ref(null)
const result = ref(null)
const error = ref('')
const busy = ref('')
const done = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    file.value = null
    result.value = null
    error.value = ''
    done.value = false
  },
)

async function run(step) {
  error.value = ''
  busy.value = step
  const form = new FormData()
  form.append('file', file.value)
  const { ok, data } = await apiUpload(`catalog/import/${step}/`, form)
  busy.value = ''
  if (!ok) {
    error.value = fieldErrors(data).file || 'Не удалось обработать файл'
    return
  }
  result.value = data
  if (step === 'commit') {
    done.value = true
    emit('imported')
  }
}
</script>
