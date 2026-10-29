<template>
  <q-card flat bordered>
    <q-card-section class="row items-center q-gutter-sm">
      <div class="text-subtitle1 col">{{ title }}</div>
      <q-select v-model="filter" :options="categories" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Категория" style="min-width: 160px" @update:model-value="load" />
    </q-card-section>

    <q-card-section v-if="can('core.add_attachment')" class="q-pt-none">
      <div class="row q-col-gutter-sm items-center">
        <q-file v-model="files" multiple outlined dense label="Выберите файлы или перетащите сюда" class="col-12 col-sm"
          :max-file-size="maxBytes" @rejected="onRejected">
          <template #prepend><q-icon name="attach_file" /></template>
        </q-file>
        <q-select v-model="uploadCategory" :options="categories" option-value="id" option-label="name" emit-value
          map-options dense outlined label="В категорию" class="col-6 col-sm-3" />
        <div class="col-6 col-sm-auto">
          <q-btn color="primary" unelevated icon="upload" label="Загрузить" :disable="!files?.length"
            :loading="uploading" @click="upload" />
        </div>
      </div>
    </q-card-section>

    <q-list separator>
      <q-item v-for="item in items" :key="item.id">
        <q-item-section avatar><q-icon :name="iconFor(item)" color="primary" /></q-item-section>
        <q-item-section>
          <q-item-label>
            <a :href="downloadUrl(item)" target="_blank" class="text-primary">{{ item.name }}</a>
          </q-item-label>
          <q-item-label caption>
            {{ [item.category_name, sizeText(item.size), formatDate(item.created_at), item.author].filter(Boolean).join(' · ') }}
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <div class="row no-wrap">
            <q-btn flat round dense icon="download" :href="`${downloadUrl(item)}?download=1`"><q-tooltip>Скачать</q-tooltip></q-btn>
            <q-btn v-if="can('core.delete_attachment')" flat round dense icon="delete" color="negative" @click="remove(item)">
              <q-tooltip>Удалить</q-tooltip>
            </q-btn>
          </div>
        </q-item-section>
      </q-item>
      <q-item v-if="!items.length">
        <q-item-section class="text-grey-7">Файлов нет</q-item-section>
      </q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// Файлы записи (клиента, питомца, позже — приёма): список, загрузка, скачивание, удаление.
// Файлы открываются только через сервер с проверкой прав — прямых ссылок нет.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiUpload, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({
  ownerType: { type: String, required: true }, // 'clients.client'
  ownerId: { type: String, required: true },
  title: { type: String, default: 'Файлы' },
})
const emit = defineEmits(['changed'])
const $q = useQuasar()
const maxBytes = 25 * 1024 * 1024
const items = ref([])
const categories = ref([])
const filter = ref(null)
const files = ref(null)
const uploadCategory = ref(null)
const uploading = ref(false)

const downloadUrl = (item) => `/api/core/attachments/${item.id}/download/`
const formatDate = (iso) => new Date(iso).toLocaleDateString('ru-RU')
function sizeText(bytes) {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}
function iconFor(item) {
  if (item.content_type.startsWith('image/')) return 'image'
  if (item.content_type === 'application/pdf') return 'picture_as_pdf'
  return 'description'
}

async function load() {
  const params = new URLSearchParams({ owner_type: props.ownerType, owner_id: props.ownerId })
  if (filter.value) params.set('category', filter.value)
  const { ok, data } = await apiGet(`core/attachments/?${params}`)
  items.value = ok ? data : []
}

function onRejected() {
  $q.notify({ type: 'negative', message: 'Файл больше 25 МБ — его не получится загрузить' })
}

async function upload() {
  uploading.value = true
  for (const file of files.value) {
    const form = new FormData()
    form.append('file', file)
    form.append('owner_type', props.ownerType)
    form.append('owner_id', props.ownerId)
    if (uploadCategory.value) form.append('category', uploadCategory.value)
    const { ok, data } = await apiUpload('core/attachments/', form)
    if (!ok) $q.notify({ type: 'negative', message: `${file.name}: ${fieldErrors(data).file || 'не загружен'}` })
  }
  uploading.value = false
  files.value = null
  load()
  emit('changed')
}

function remove(item) {
  $q.dialog({
    title: 'Удалить файл?',
    message: `«${item.name}»`,
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
  }).onOk(async () => {
    const { ok } = await apiDelete(`core/attachments/${item.id}/`)
    if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось удалить файл' })
    load()
    emit('changed')
  })
}

onMounted(async () => {
  categories.value = (await apiGet('core/file-categories/?active=true')).data ?? []
  load()
})

defineExpose({ load })
</script>
