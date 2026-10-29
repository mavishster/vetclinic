<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="text-subtitle1 col">Записи на приём</div>
      <q-btn v-if="can('scheduling.add_appointment')" flat dense color="primary" icon="event" label="Записать"
        @click="open = true" />
    </q-card-section>
    <q-list separator>
      <q-item v-for="item in items" :key="item.id">
        <q-item-section side class="text-weight-medium">
          {{ new Date(item.start).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) }} {{ timeOf(item.start) }}
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ [item.pet_name, item.purpose_name].filter(Boolean).join(' · ') || 'Приём' }}</q-item-label>
          <q-item-label caption>{{ item.doctor_name || 'любой врач' }}</q-item-label>
        </q-item-section>
        <q-item-section side><q-badge :color="STATUS[item.status].color" :label="item.status_label" /></q-item-section>
      </q-item>
      <q-item v-if="!items.length"><q-item-section class="text-grey-7">Предстоящих записей нет</q-item-section></q-item>
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

const props = defineProps({ client: { type: Object, required: true } })
const items = ref([])
const open = ref(false)

async function load() {
  items.value = (await apiGet(`scheduling/appointments/?client=${props.client.id}&upcoming=1`)).data ?? []
}
onMounted(load)
</script>
