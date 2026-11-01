<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Стационар</h1>
      <q-btn-toggle v-model="status" no-caps unelevated toggle-color="primary" @update:model-value="load"
        :options="[{ label: 'В стационаре', value: 'active' }, { label: 'Выписанные', value: 'discharged' }]" />
      <q-btn v-if="can('inpatient.add_hospitalization')" color="primary" unelevated icon="local_hotel" label="Принять" @click="admitOpen = true" />
    </div>

    <div class="row q-col-gutter-md">
      <div v-for="h in rows" :key="h.id" class="col-12 col-sm-6 col-lg-4">
        <q-card flat bordered class="cursor-pointer full-height" @click="$router.push(`/inpatient/${h.id}`)">
          <q-card-section>
            <div class="row items-center no-wrap">
              <div class="col">
                <div class="text-h6">{{ h.pet_name }} <span class="text-caption text-grey-7">{{ h.species }}</span></div>
                <div class="text-caption text-grey-7">{{ h.client_name }}</div>
              </div>
              <q-badge v-if="h.tasks_today.overdue" color="negative" :label="`просрочено: ${h.tasks_today.overdue}`" />
            </div>
            <div class="q-mt-sm">
              <q-icon name="meeting_room" size="16px" /> {{ h.ward_name }}{{ h.place ? `, место ${h.place}` : '' }}
              · <b>{{ h.status === 'active' ? `${h.days}-е сутки` : `${h.days} сут.` }}</b> · {{ h.doctor_name }}
            </div>
            <div v-if="h.reason" class="text-caption ellipsis-2-lines q-mt-xs">{{ h.reason }}</div>
            <div v-if="h.status === 'active'" class="row items-center q-mt-sm q-gutter-x-md text-caption">
              <span><q-icon name="checklist" size="16px" /> сегодня {{ h.tasks_today.done }} из {{ h.tasks_today.total }}</span>
              <span v-if="h.last_observation?.temperature"><q-icon name="device_thermostat" size="16px" /> {{ h.last_observation.temperature }} °C</span>
            </div>
            <div v-else class="text-caption q-mt-sm">выписан {{ new Date(h.discharged_at).toLocaleDateString('ru-RU') }}</div>
          </q-card-section>
        </q-card>
      </div>
      <div v-if="!rows.length && !loading" class="col-12 text-grey-7">
        {{ status === 'active' ? 'В стационаре никого нет' : 'Выписанных пока нет' }}
      </div>
    </div>
    <AdmitDialog v-model="admitOpen" />
  </q-page>
</template>

<script setup>
// Стационар: пациенты карточками — палата, сутки, врач, отметки на сегодня, температура.
import { onMounted, onUnmounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import AdmitDialog from './AdmitDialog.vue'

const rows = ref([])
const loading = ref(false)
const status = ref('active')
const admitOpen = ref(false)

async function load() {
  loading.value = true
  rows.value = (await apiGet(`inpatient/hospitalizations/?status=${status.value}`)).data ?? []
  loading.value = false
}
let timer = null
onMounted(() => {
  load()
  timer = setInterval(load, 60000) // отметки персонала обновляются раз в минуту
})
onUnmounted(() => clearInterval(timer))
</script>
