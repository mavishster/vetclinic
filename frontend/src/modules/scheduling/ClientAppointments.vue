<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="text-subtitle1 col">{{ history ? 'История записей на приём' : 'Записи на приём' }}</div>
      <q-btn v-if="can('scheduling.add_appointment')" flat dense color="primary" icon="event" label="Записать"
        @click="open = true" />
    </q-card-section>
    <q-list separator>
      <q-item v-for="item in items" :key="item.id" :class="{ 'text-grey-7': history && new Date(item.end) < new Date() }">
        <q-item-section side class="text-weight-medium">
          {{ new Date(item.start).toLocaleDateString('ru-RU', history ? { day: 'numeric', month: 'short', year: '2-digit' } : { day: 'numeric', month: 'short' }) }} {{ timeOf(item.start) }}
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ [item.pet_name, item.purpose_name].filter(Boolean).join(' · ') || 'Приём' }}</q-item-label>
          <q-item-label caption>{{ item.doctor_name || 'любой врач' }}</q-item-label>
        </q-item-section>
        <q-item-section side><q-badge :color="STATUS[item.status].color" :label="item.status_label" /></q-item-section>
      </q-item>
      <q-item v-if="!items.length"><q-item-section class="text-grey-7">{{ history ? 'Записей ещё не было' : 'Предстоящих записей нет' }}</q-item-section></q-item>
    </q-list>
    <AppointmentDialog v-model="open" :preset="{ client: client.id, clientName: client.full_name }" @saved="load" />
  </q-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import AppointmentDialog from './AppointmentDialog.vue'
import { STATUS, timeOf } from './appointments'

// history — все записи (будущие сверху, затем прошедшие), иначе — только предстоящие.
const props = defineProps({ client: { type: Object, required: true }, history: { type: Boolean, default: false } })
const items = ref([])
const open = ref(false)
defineExpose({ load })

async function load() {
  const list = (await apiGet(`scheduling/appointments/?client=${props.client.id}${props.history ? '' : '&upcoming=1'}`)).data ?? []
  items.value = props.history ? [...list].sort((a, b) => b.start.localeCompare(a.start)) : list
}
onMounted(load)
</script>
