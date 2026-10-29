<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Клиенты</h1>
      <q-btn v-if="can('clients.add_client')" color="primary" icon="person_add" label="Новый клиент" unelevated
        @click="editorOpen = true" />
    </div>

    <div class="row q-col-gutter-sm q-mb-md items-center">
      <q-input v-model="search" dense outlined clearable debounce="300" autofocus
        placeholder="ФИО, телефон, № по журналу, дисконтная карта" class="col-12 col-md-5"
        @update:model-value="reload">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-select v-model="city" :options="cities" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Город" class="col-6 col-md-2" @update:model-value="reload" />
      <q-select v-model="clientType" :options="types" option-value="id" option-label="name" emit-value map-options
        dense outlined clearable label="Тип" class="col-6 col-md-2" @update:model-value="reload" />
      <q-btn-toggle v-model="status" :options="statusOptions" no-caps unelevated toggle-color="primary"
        class="col-auto" @update:model-value="reload" />
      <q-checkbox v-model="blacklist" label="Чёрный список" dense class="col-auto" @update:model-value="reload" />
    </div>

    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading"
      flat bordered binary-state-sort :rows-per-page-options="[25, 50, 100]" no-data-label="Клиенты не найдены"
      rows-per-page-label="Строк на странице" @request="onRequest" @row-click="(e, row) => open(row)">
      <template #body-cell-full_name="props">
        <q-td :props="props" :class="{ 'text-grey-6': props.row.status === 'inactive' }">
          <span class="text-weight-medium">{{ props.row.full_name }}</span>
          <q-badge v-for="badge in clientBadges(props.row)" :key="badge.label" :color="badge.color"
            :label="badge.label" class="q-ml-sm" />
        </q-td>
      </template>
    </q-table>

    <ClientEditDialog v-model="editorOpen" @saved="open" />
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api'
import { can } from '@/session'
import ClientEditDialog from './ClientEditDialog.vue'
import { clientBadges } from './statuses'

const router = useRouter()
const rows = ref([])
const loading = ref(false)
const search = ref('')
const city = ref(null)
const clientType = ref(null)
const status = ref('active,temporary')
const blacklist = ref(false)
const cities = ref([])
const types = ref([])
const editorOpen = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })

const statusOptions = [
  { label: 'Активные', value: 'active,temporary' },
  { label: 'Неактивные', value: 'inactive' },
  { label: 'Все', value: '' },
]
const primaryPhone = (row) => (row.phones.find((p) => p.is_primary) ?? row.phones[0])?.number ?? ''
const columns = [
  { name: 'full_name', label: 'Клиент', field: 'full_name', align: 'left' },
  { name: 'phone', label: 'Телефон', field: primaryPhone, align: 'left' },
  { name: 'city', label: 'Город', field: 'city_name', align: 'left' },
  { name: 'type', label: 'Тип', field: 'client_type_name', align: 'left' },
  { name: 'journal', label: '№ по журналу', field: 'journal_number', align: 'left' },
]

async function onRequest({ pagination: next }) {
  loading.value = true
  const params = new URLSearchParams({ page: next.page, page_size: next.rowsPerPage })
  if (search.value) params.set('search', search.value)
  if (status.value) params.set('status', status.value)
  if (city.value) params.set('city', city.value)
  if (clientType.value) params.set('client_type', clientType.value)
  if (blacklist.value) params.set('blacklist', 'true')
  const { ok, data } = await apiGet(`clients/clients/?${params}`)
  rows.value = ok ? data.results : []
  pagination.value = { ...next, rowsNumber: ok ? data.count : 0 }
  loading.value = false
}

const reload = () => onRequest({ pagination: { ...pagination.value, page: 1 } })
const open = (client) => router.push(`/clients/${client.id}`)

onMounted(async () => {
  const [c, t] = await Promise.all([apiGet('clients/cities/?active=true'), apiGet('clients/client-types/?active=true')])
  cities.value = c.data ?? []
  types.value = t.data ?? []
  reload()
})
</script>
