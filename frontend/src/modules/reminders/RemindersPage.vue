<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Напоминания</h1>
      <q-btn flat round icon="refresh" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
    </div>
    <p class="text-grey-8">
      Список собирается сам: подходит срок профилактики (за {{ days }} дней), завтрашние записи на приём, повторные приёмы,
      назначенные врачом. Если клиент записался или процедуру уже сделали — напоминание уходит из списка само.
    </p>
    <q-btn-toggle v-model="kind" no-caps unelevated toggle-color="primary" class="q-mb-md" @update:model-value="load"
      :options="[{ label: 'Все', value: '' }, { label: 'Профилактика', value: 'prevention' }, { label: 'Записи на завтра', value: 'appointment' }, { label: 'Повторные приёмы', value: 'revisit' }]" />

    <q-table :rows="rows" :columns="columns" row-key="id" flat bordered :loading="loading" :pagination="{ rowsPerPage: 50 }"
      no-data-label="Сегодня обзванивать некого" rows-per-page-label="Строк на странице">
      <template #body-cell-due="props">
        <q-td :props="props" :class="props.row.overdue ? 'text-negative text-weight-medium' : ''">
          {{ new Date(props.row.due_date).toLocaleDateString('ru-RU') }}
          <div v-if="props.row.overdue" class="text-caption">срок прошёл</div>
        </q-td>
      </template>
      <template #body-cell-client="props">
        <q-td :props="props">
          <router-link :to="`/clients/${props.row.client}`" class="text-primary">{{ props.row.client_name }}</router-link>
          <div v-if="props.row.phone"><a :href="`tel:${props.row.phone}`" class="text-weight-medium">{{ props.row.phone }}</a></div>
        </q-td>
      </template>
      <template #body-cell-text="props">
        <q-td :props="props">
          <q-badge :color="KIND[props.row.kind].color" :label="props.row.kind_label" class="q-mr-xs" />
          {{ props.row.pet_name ? `${props.row.pet_name}: ` : '' }}{{ props.row.text }}
          <div v-if="props.row.attempts" class="text-caption text-warning">
            не дозвонились: {{ props.row.attempts }} раз{{ props.row.last_contact_at ? `, последний — ${fmt(props.row.last_contact_at)}` : '' }}
          </div>
          <div v-if="props.row.note" class="text-caption text-grey-7">{{ props.row.note }}</div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right text-no-wrap">
          <template v-if="can('reminders.change_reminder')">
            <q-btn v-if="props.row.kind !== 'appointment' && can('scheduling.add_appointment')" dense unelevated color="primary"
              icon="event" label="Записать" no-caps class="q-mr-xs" @click="book(props.row)" />
            <q-btn dense flat icon="phone_missed" color="warning" @click="mark(props.row, 'no_answer')"><q-tooltip>Не дозвонились</q-tooltip></q-btn>
            <q-btn dense flat icon="task_alt" color="positive" @click="mark(props.row, 'done')"><q-tooltip>Напомнили</q-tooltip></q-btn>
            <q-btn dense flat icon="do_not_disturb_on" color="grey-7" @click="decline(props.row)"><q-tooltip>Отказ</q-tooltip></q-btn>
          </template>
        </q-td>
      </template>
    </q-table>

    <AppointmentDialog v-model="bookOpen" :preset="preset" @saved="booked" />
  </q-page>
</template>

<script setup>
// Обзвон по напоминаниям: кому, о чём, телефон; итог звонка — одной кнопкой.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost } from '@/api'
import { can } from '@/session'
// Запись на приём — окно модуля «Календарь».
import AppointmentDialog from '@/modules/scheduling/AppointmentDialog.vue'

const $q = useQuasar()
const KIND = { prevention: { color: 'positive' }, appointment: { color: 'primary' }, revisit: { color: 'deep-orange' } }
const days = 7
const kind = ref('')
const rows = ref([])
const loading = ref(false)
const bookOpen = ref(false)
const preset = ref({})
let bookingFor = null
const fmt = (iso) => new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const columns = [
  { name: 'due', label: 'Срок', field: 'due_date', align: 'left' },
  { name: 'client', label: 'Клиент', field: 'client_name', align: 'left' },
  { name: 'text', label: 'О чём', field: 'text', align: 'left' },
  { name: 'actions', label: '', field: 'id' },
]

async function load() {
  loading.value = true
  rows.value = (await apiGet(`reminders/reminders/${kind.value ? `?kind=${kind.value}` : ''}`)).data ?? []
  loading.value = false
}

async function mark(row, status, note = '') {
  const { ok } = await apiPost(`reminders/reminders/${row.id}/mark/`, { status, note })
  if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось сохранить' })
  load()
}

function decline(row) {
  $q.dialog({
    title: 'Клиент отказался', message: 'Причина (необязательно)', prompt: { model: '', type: 'text' },
    cancel: { label: 'Назад', flat: true }, ok: { label: 'Сохранить', color: 'primary', unelevated: true },
  }).onOk((note) => mark(row, 'declined', note))
}

function book(row) {
  bookingFor = row
  const start = new Date(row.due_date)
  start.setHours(10, 0, 0, 0)
  preset.value = { client: row.client, clientName: row.client_name, start: start < new Date() ? new Date() : start }
  bookOpen.value = true
}

function booked() {
  if (bookingFor) mark(bookingFor, 'booked', 'записали при обзвоне')
  bookingFor = null
}

onMounted(load)
</script>
