<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card v-if="appointment" style="width: 480px; max-width: 95vw">
      <q-card-section class="row items-start">
        <div class="col">
          <div class="text-h6">{{ timeOf(appointment.start) }}–{{ timeOf(appointment.end) }}
            <q-badge :color="STATUS[appointment.status].color" :label="appointment.status_label" class="q-ml-xs" />
            <q-badge v-if="appointment.is_overdue" color="negative" label="просрочен" class="q-ml-xs" />
          </div>
          <div class="text-caption text-grey-7">{{ new Date(appointment.start).toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' }) }}</div>
        </div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-list dense>
        <q-item clickable :to="`/clients/${appointment.client}`">
          <q-item-section avatar><q-icon name="person" color="primary" /></q-item-section>
          <q-item-section>
            <q-item-label>{{ appointment.client_name }}
              <q-badge v-if="appointment.client_status === 'temporary'" color="warning" label="временный" />
            </q-item-label>
            <q-item-label caption>{{ appointment.client_phone }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-if="appointment.pet_name" :clickable="!!appointment.pet" :to="appointment.pet ? `/pets/${appointment.pet}` : undefined">
          <q-item-section avatar><q-icon name="pets" color="primary" /></q-item-section>
          <q-item-section>{{ appointment.pet_name }}<q-item-label v-if="!appointment.pet" caption>со слов, карточки нет</q-item-label></q-item-section>
        </q-item>
        <q-item v-if="appointment.purpose_name">
          <q-item-section avatar><q-icon name="flag" :style="{ color: appointment.purpose_color }" /></q-item-section>
          <q-item-section>{{ appointment.purpose_name }}</q-item-section>
        </q-item>
        <q-item>
          <q-item-section avatar><q-icon name="medical_services" color="primary" /></q-item-section>
          <q-item-section>{{ appointment.doctor_name || 'Любой врач' }}</q-item-section>
        </q-item>
        <q-item v-if="appointment.note">
          <q-item-section avatar><q-icon name="notes" color="primary" /></q-item-section>
          <q-item-section style="white-space: pre-line">{{ appointment.note }}</q-item-section>
        </q-item>
        <q-item v-if="appointment.cancel_reason">
          <q-item-section avatar><q-icon name="info" color="grey-7" /></q-item-section>
          <q-item-section>Причина отмены: {{ appointment.cancel_reason }}</q-item-section>
        </q-item>
      </q-list>
      <q-card-actions v-if="can('scheduling.change_appointment')" class="q-px-md q-pb-md column items-stretch q-gutter-y-xs">
        <q-btn v-for="action in ACTIONS[appointment.status]" :key="action.to" :icon="action.icon" :label="action.label"
          :color="action.to === 'cancelled' ? 'negative' : 'primary'" :outline="action.to !== primaryAction" unelevated
          no-caps align="left" @click="go(action.to)" />
        <q-btn flat icon="edit" label="Изменить запись" no-caps align="left" @click="emit('edit', appointment)" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { can } from '@/session'
import { ACTIONS, changeStatus, STATUS, timeOf } from './appointments'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  appointment: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'changed', 'edit'])
const $q = useQuasar()
const primaryAction = computed(() => ACTIONS[props.appointment?.status]?.[0]?.to)

async function go(to) {
  const updated = await changeStatus($q, props.appointment, to)
  if (updated) {
    emit('changed', updated)
    emit('update:modelValue', false)
  }
}
</script>
