<template>
  <q-card v-if="items.length" flat bordered>
    <q-card-section class="text-subtitle1">Напоминания</q-card-section>
    <q-list dense separator>
      <q-item v-for="r in items" :key="r.id">
        <q-item-section>
          <q-item-label>{{ r.pet_name ? `${r.pet_name}: ` : '' }}{{ r.text }}</q-item-label>
          <q-item-label caption>
            {{ r.status_label }}{{ r.last_contact_at ? ` · ${new Date(r.last_contact_at).toLocaleDateString('ru-RU')}` : '' }}{{ r.contacted_by_name ? ` · ${r.contacted_by_name}` : '' }}{{ r.note ? ` · ${r.note}` : '' }}
          </q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// История напоминаний в карточке клиента (модуль «Напоминания»).
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({ client: { type: Object, required: true } })
const items = ref([])
onMounted(async () => {
  items.value = ((await apiGet(`reminders/reminders/?client=${props.client.id}`)).data ?? []).slice(0, 10)
})
</script>
