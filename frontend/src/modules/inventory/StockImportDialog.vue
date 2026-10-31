<template>
  <q-dialog :model-value="modelValue" :maximized="$q.screen.lt.md" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 960px; max-width: 98vw">
      <q-card-section class="row items-center">
        <div class="text-h6 col">Импорт остатков</div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-card-section class="q-pt-none text-body2">
        Excel (.xlsx) или CSV — например, выгрузка остатков из VetManager. Нужны колонки «Количество» и «Закупочная цена»,
        а товар узнаётся по «Штрихкоду», «Артикулу» или «Названию» (что есть). По желанию — «Единица», «Серия», «Срок годности».
        Из найденных строк создастся <b>черновик прихода</b> — его можно проверить и выполнить.
        Товары, которых нет в каталоге, сначала заведите (например, импортом прайса).
        <div class="q-mt-sm"><a href="/api/inventory/import/template/" class="text-primary">Скачать шаблон</a></div>
      </q-card-section>
      <q-card-section class="q-pt-none">
        <div class="row q-col-gutter-sm items-center">
          <q-select v-model="warehouse" :options="warehouses" option-value="id" option-label="name" emit-value map-options
            outlined dense label="На склад" class="col-12 col-sm-3" />
          <q-file v-model="file" outlined dense accept=".xlsx,.csv" label="Файл остатков" class="col-12 col-sm"
            @update:model-value="result = null"><template #prepend><q-icon name="table_view" /></template></q-file>
          <div class="col-auto">
            <q-btn outline color="primary" icon="fact_check" label="Проверить" :disable="!file" :loading="busy === 'preview'" @click="run('preview')" />
          </div>
        </div>
        <div v-if="error" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>
      <q-card-section v-if="result" class="q-pt-none">
        <div class="row q-gutter-sm q-mb-sm">
          <q-chip color="positive" text-color="white" :label="`готово к загрузке: ${result.ready}`" />
          <q-chip :color="result.errors ? 'negative' : 'grey-5'" text-color="white" :label="`с ошибками: ${result.errors}`" />
          <q-chip color="primary" text-color="white" :label="`на сумму ${money(result.sum)}`" />
        </div>
        <q-table :rows="result.rows" :columns="columns" row-key="line" flat bordered dense :pagination="{ rowsPerPage: 20 }"
          rows-per-page-label="Строк на странице">
          <template #body-cell-status="props">
            <q-td :props="props">
              <q-badge v-if="!props.row.error" color="positive" label="найден" />
              <span v-else class="text-negative">{{ props.row.error }}</span>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn v-if="result" color="primary" unelevated icon="move_to_inbox" :label="`Создать приход (${result.ready})`"
          :disable="!result.ready || !warehouse" :loading="busy === 'commit'" @click="run('commit')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Импорт остатков из Excel / CSV → черновик прихода «Ввод остатков».
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiUpload, fieldErrors } from '@/api'
import { money } from '@/modules/catalog/money'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])
const router = useRouter()
const warehouses = ref([])
const warehouse = ref(null)
const file = ref(null)
const result = ref(null)
const error = ref('')
const busy = ref('')
const columns = [
  { name: 'line', label: 'Строка', field: 'line', align: 'left' },
  { name: 'name', label: 'В файле', field: 'name', align: 'left' },
  { name: 'item', label: 'Нашёлся товар', field: 'item_name', align: 'left' },
  { name: 'unit', label: 'Ед.', field: 'unit', align: 'left' },
  { name: 'qty', label: 'Кол-во', field: (r) => (r.quantity ? Number(r.quantity) : ''), align: 'right' },
  { name: 'price', label: 'Цена', field: (r) => (r.price ? money(r.price) : ''), align: 'right' },
  { name: 'series', label: 'Серия', field: 'series', align: 'left' },
  { name: 'status', label: '', field: 'error', align: 'left' },
]

watch(() => props.modelValue, async (open) => {
  if (!open) return
  file.value = result.value = null
  error.value = ''
  warehouses.value = (await apiGet('inventory/warehouses/?active=true')).data ?? []
  warehouse.value = warehouse.value || warehouses.value[0]?.id || null
})

async function run(step) {
  error.value = ''
  busy.value = step
  const form = new FormData()
  form.append('file', file.value)
  if (step === 'commit') form.append('warehouse', warehouse.value)
  const { ok, data } = await apiUpload(`inventory/import/${step}/`, form)
  busy.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось обработать файл')
  result.value = data
  if (step === 'commit') {
    emit('update:modelValue', false)
    router.push(`/inventory/documents/${data.document}`)
  }
}
</script>
