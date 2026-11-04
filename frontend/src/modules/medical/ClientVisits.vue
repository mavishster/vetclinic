<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="text-subtitle1 col">Медкарты</div>
      <span class="text-caption text-grey-7">последние приёмы питомцев клиента</span>
    </q-card-section>
    <q-list separator>
      <q-item v-for="v in visits" :key="v.id" clickable :to="`/visits/${v.id}`">
        <q-item-section side class="text-weight-medium" style="min-width: 88px">
          {{ new Date(v.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: '2-digit' }) }}
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ [v.pet_name, v.purpose_name].filter(Boolean).join(' · ') }}</q-item-label>
          <q-item-label caption>
            {{ v.doctor_name }}<template v-if="v.diagnoses?.length"> · {{ v.diagnoses.map((d) => d.diagnosis_name || d.text).filter(Boolean).join(', ') }}</template>
          </q-item-label>
        </q-item-section>
        <q-item-section side><q-icon name="chevron_right" /></q-item-section>
      </q-item>
      <q-item v-if="!visits.length && !loading"><q-item-section class="text-grey-7">Приёмов пока не было</q-item-section></q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// Медкарты клиента (модуль «Медкарта»): последние приёмы всех его питомцев, по клику — запись.
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({ client: { type: Object, required: true } })
const visits = ref([])
const loading = ref(true)

onMounted(async () => {
  const { data } = await apiGet(`medical/visits/?client=${props.client.id}&page_size=10`)
  visits.value = (data?.results ?? data ?? []).slice(0, 10)
  loading.value = false
})
</script>
