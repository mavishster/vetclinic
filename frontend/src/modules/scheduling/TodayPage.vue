<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Приёмы сегодня</h1>
      <q-btn flat round icon="refresh" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
      <q-btn v-if="canAdd" outline color="primary" icon="directions_walk" label="Клиент без записи" @click="walkInOpen = true" />
      <q-btn v-if="canAdd" color="primary" unelevated icon="add" label="Записать" @click="bookOpen = true" />
    </div>

    <div class="row q-col-gutter-md">
      <div v-for="group in groups" :key="group.key" class="col-12 col-md-6 col-lg-4">
        <q-card flat bordered>
          <q-card-section class="row items-center q-py-sm">
            <div class="text-subtitle1 col">{{ group.title }}</div>
            <q-badge :color="group.color" :label="group.items.length" />
          </q-card-section>
          <q-list separator>
            <q-item v-for="item in group.items" :key="item.id" clickable @click="openView(item)"
              :class="{ 'row-highlight-negative': item.is_overdue }">
              <q-item-section side class="text-weight-medium">{{ timeOf(item.start) }}</q-item-section>
              <q-item-section>
                <q-item-label>
                  <q-badge v-if="item.queue_number && ['waiting', 'in_progress'].includes(item.status)" color="primary" outline
                    :label="`№ ${item.queue_number}`" class="q-mr-xs" />
                  {{ item.client_name }}
                  <q-badge v-if="item.client_status === 'temporary'" color="warning" label="временный" />
                </q-item-label>
                <q-item-label caption>
                  {{ [item.pet_name, item.purpose_name, item.doctor_name || 'любой врач'].filter(Boolean).join(' · ') }}
                </q-item-label>
                <q-item-label v-if="item.is_overdue" caption class="text-negative">время прошло — отметьте «пришёл» или «не пришёл»</q-item-label>
                <q-item-label v-if="item.status === 'waiting' && item.called_at" caption class="text-positive">
                  приглашён в {{ timeOf(item.called_at) }} · {{ item.room_name }}
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="canChange && ACTIONS[item.status][0]" side>
                <div class="row no-wrap q-gutter-xs">
                  <q-btn v-if="item.status === 'waiting'" dense unelevated color="positive" icon="campaign" @click.stop="invite(item)">
                    <q-tooltip>{{ item.called_at ? 'Пригласить ещё раз' : 'Пригласить в кабинет' }}</q-tooltip>
                  </q-btn>
                  <q-btn dense unelevated color="primary" :icon="ACTIONS[item.status][0].icon" @click.stop="quick(item)">
                    <q-tooltip>{{ ACTIONS[item.status][0].label }}</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
            <q-item v-if="!group.items.length"><q-item-section class="text-grey-6">Нет</q-item-section></q-item>
          </q-list>
        </q-card>
      </div>
    </div>

    <AppointmentDialog v-model="bookOpen" :doctors="doctors" @saved="load" />
    <AppointmentDialog v-model="walkInOpen" walk-in :doctors="doctors" @saved="load" />
    <AppointmentDialog v-model="editOpen" :appointment="editing" :doctors="doctors" @saved="load" />
    <AppointmentView v-model="viewOpen" :appointment="viewing" @changed="load" @edit="edit" />
  </q-page>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet } from '@/api'
import { can } from '@/session'
import AppointmentDialog from './AppointmentDialog.vue'
import AppointmentView from './AppointmentView.vue'
import { ACTIONS, byQueue, changeStatus, inviteToRoom, isoDate, timeOf } from './appointments'

const $q = useQuasar()
const canAdd = can('scheduling.add_appointment')
const canChange = can('scheduling.change_appointment')
const items = ref([])
const doctors = ref([])
const bookOpen = ref(false)
const walkInOpen = ref(false)
const editOpen = ref(false)
const editing = ref(null)
const viewOpen = ref(false)
const viewing = ref(null)

const byStatus = (...statuses) => items.value.filter((i) => statuses.includes(i.status))
const groups = computed(() => [
  { key: 'waiting', title: 'Ожидают', color: 'warning', items: byStatus('waiting').sort(byQueue) },
  { key: 'in_progress', title: 'У врача', color: 'info', items: byStatus('in_progress') },
  { key: 'planned', title: 'Записаны', color: 'primary', items: byStatus('planned') },
  { key: 'completed', title: 'Приняты', color: 'positive', items: byStatus('completed') },
  { key: 'missed', title: 'Отменены и не пришли', color: 'grey-6', items: byStatus('cancelled', 'no_show') },
])

async function load() {
  const today = isoDate(new Date())
  const { data } = await apiGet(`scheduling/calendar/?date=${today}`)
  items.value = data?.appointments ?? []
  doctors.value = (data?.doctors ?? []).map((d) => ({ id: d.id, name: d.name }))
}

async function quick(item) {
  if (await changeStatus($q, item, ACTIONS[item.status][0].to)) load()
}
async function invite(item) {
  if (await inviteToRoom($q, item)) load()
}
function openView(item) {
  viewing.value = item
  viewOpen.value = true
}
function edit(item) {
  viewOpen.value = false
  editing.value = item
  editOpen.value = true
}

let timer = null
onMounted(() => {
  load()
  timer = setInterval(load, 30000) // очередь обновляется сама раз в полминуты
})
onUnmounted(() => clearInterval(timer))
</script>
