<template>
  <div>
    <q-banner dense rounded class="row-highlight-primary q-mb-md">
      <template #avatar><q-icon name="biotech" color="primary" /></template>
      Номер для анализатора: <b class="text-h6">{{ visit.lab_code }}</b> — введите его в прибор, и результат придёт сюда сам.
    </q-banner>
    <q-btn-toggle v-model="scope" no-caps unelevated dense toggle-color="primary" class="q-mb-md" @update:model-value="load"
      :options="[{ label: 'Этот приём', value: 'visit' }, { label: 'Все анализы питомца', value: 'pet' }]" />
    <LabResultCard v-for="r in results" :key="r.id" :result="r" @history="openHistory" />
    <div v-if="!results.length" class="text-grey-7">{{ scope === 'visit' ? 'Анализов по этому приёму пока нет' : 'Анализов у питомца пока нет' }}</div>
    <HistoryDialog v-model="historyOpen" :value="historyValue" :pet-id="visit.pet" />
  </div>
</template>

<script setup>
// Вкладка «Анализы» в медкарте (модуль «Лаборатория»): результаты приёма или все анализы питомца.
import { onMounted, onUnmounted, ref } from 'vue'
import { apiGet } from '@/api'
import HistoryDialog from './HistoryDialog.vue'
import LabResultCard from './LabResultCard.vue'

const props = defineProps({ visit: { type: Object, required: true } })
const scope = ref('visit')
const results = ref([])
const historyOpen = ref(false)
const historyValue = ref(null)

async function load() {
  const query = scope.value === 'visit' ? `visit=${props.visit.id}` : `pet=${props.visit.pet}`
  results.value = (await apiGet(`laboratory/results/?${query}`)).data ?? []
}
function openHistory(value) {
  historyValue.value = value
  historyOpen.value = true
}
let timer = null
onMounted(() => {
  load()
  timer = setInterval(load, 30000) // результат с прибора появится без перезагрузки
})
onUnmounted(() => clearInterval(timer))
</script>
