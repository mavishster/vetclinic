<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Подписанные документы</h1>
      <q-btn flat round icon="refresh" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
    </div>
    <p class="text-grey-8">Договоры и согласия, подписанные клиентами на планшете. PDF с подписью и сведениями о подписании хранится в файлах клиента.</p>

    <div class="row q-col-gutter-sm items-center q-mb-md">
      <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Клиент или документ" class="col-12 col-md-3" @update:model-value="load">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-select v-model="purpose" :options="PURPOSES" emit-value map-options dense outlined clearable label="Вид документа" class="col-6 col-md-2" @update:model-value="load" />
      <q-input v-model="from" type="date" dense outlined stack-label label="С" class="col-6 col-md-2" @update:model-value="load" />
      <q-input v-model="to" type="date" dense outlined stack-label label="По" class="col-6 col-md-2" @update:model-value="load" />
      <q-btn-toggle v-model="status" no-caps unelevated dense toggle-color="primary" class="col-auto" @update:model-value="load"
        :options="[{ label: 'Подписаны', value: 'signed' }, { label: 'Ждут подписи', value: 'pending' }, { label: 'Отменены', value: 'cancelled' }, { label: 'Все', value: '' }]" />
    </div>

    <q-table :rows="rows" :columns="columns" row-key="id" flat bordered :loading="loading" :pagination="{ rowsPerPage: 50 }"
      no-data-label="Документов нет" rows-per-page-label="Строк на странице">
      <template #body-cell-client="props">
        <q-td :props="props"><router-link :to="`/clients/${props.row.client}`" class="text-primary">{{ props.row.client_name }}</router-link></q-td>
      </template>
      <template #body-cell-purpose="props">
        <q-td :props="props"><q-badge :color="PURPOSE_COLOR[props.row.purpose]" outline :label="PURPOSE_SHORT[props.row.purpose]" /></q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props"><q-badge :color="STATUS_COLOR[props.row.status]" :label="props.row.status_label" /></q-td>
      </template>
      <template #body-cell-pdf="props">
        <q-td :props="props" class="text-right">
          <q-btn v-if="props.row.result && can('core.view_attachment')" flat dense round icon="picture_as_pdf" color="primary"
            :href="`/api/core/attachments/${props.row.result}/download/`" target="_blank"><q-tooltip>Открыть PDF</q-tooltip></q-btn>
        </q-td>
      </template>
    </q-table>
    <div class="text-caption text-grey-7 q-mt-sm">Показываются последние 500 документов по выбранным фильтрам.</div>
  </q-page>
</template>

<script setup>
// Журнал документов, подписанных на планшете: фильтры по виду, статусу, датам и клиенту.
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'

const PURPOSES = [
  { value: 'contract', label: 'Договоры' }, { value: 'consent', label: 'Согласия на ПДн и фото' }, { value: 'other', label: 'Другие документы' },
]
const PURPOSE_COLOR = { contract: 'primary', consent: 'positive', other: 'grey-7' }
const PURPOSE_SHORT = { contract: 'договор', consent: 'согласие ПДн', other: 'другое' }
const STATUS_COLOR = { signed: 'positive', pending: 'warning', cancelled: 'grey-6' }
const fmt = (v) => (v ? new Date(v).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '')
const columns = [
  { name: 'date', label: 'Подписан', field: (r) => fmt(r.signed_at) || `отправлен ${fmt(r.created_at)}`, align: 'left', sortable: true, sort: (a, b) => a.localeCompare(b) },
  { name: 'client', label: 'Клиент', field: 'client_name', align: 'left', sortable: true },
  { name: 'title', label: 'Документ', field: 'title', align: 'left' },
  { name: 'purpose', label: 'Вид', field: 'purpose_label', align: 'left' },
  { name: 'status', label: 'Статус', field: 'status_label', align: 'left' },
  { name: 'station', label: 'Планшет', field: 'station_name', align: 'left' },
  { name: 'sent_by', label: 'Отправил', field: 'sent_by_name', align: 'left' },
  { name: 'pdf', label: '', field: 'result' },
]
const rows = ref([])
const loading = ref(false)
const search = ref('')
const purpose = ref(null)
const status = ref('signed')
const from = ref('')
const to = ref('')

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (search.value) params.set('search', search.value)
  if (purpose.value) params.set('purpose', purpose.value)
  if (status.value) params.set('status', status.value)
  if (from.value) params.set('from', from.value)
  if (to.value) params.set('to', to.value)
  rows.value = (await apiGet(`clients/signatures/?${params}`)).data ?? []
  loading.value = false
}

onMounted(load)
</script>
