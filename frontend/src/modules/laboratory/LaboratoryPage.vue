<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Лаборатория</h1>
      <q-btn flat round icon="refresh" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
    </div>
    <q-tabs v-model="tab" dense align="left" no-caps active-color="primary" indicator-color="primary" @update:model-value="load">
      <q-tab name="unassigned" :label="`Нераспределённые${unassigned ? ` (${unassigned})` : ''}`" />
      <q-tab name="all" label="Все результаты" />
    </q-tabs>
    <q-separator class="q-mb-md" />
    <p v-if="tab === 'unassigned'" class="text-grey-8">
      Результаты, у которых номер, введённый в прибор, не совпал ни с одной записью медкарты (опечатка или не ввели номер).
      Укажите правильный номер приёма — результат перейдёт в медкарту.
    </p>
    <LabResultCard v-for="r in results" :key="r.id" :result="r" show-pet @history="openHistory">
      <template #actions>
        <span v-if="r.status === 'unassigned'" class="text-caption text-grey-7 q-mx-sm">введено в прибор: «{{ r.code_entered || '—' }}»</span>
        <q-btn v-if="r.status === 'unassigned' && can('laboratory.change_labresult')" dense unelevated color="primary" icon="link"
          label="В медкарту" no-caps @click="assign(r)" />
        <q-btn v-else-if="r.visit" flat dense no-caps icon="open_in_new" label="Медкарта" :to="`/visits/${r.visit}`" />
      </template>
    </LabResultCard>
    <div v-if="!results.length" class="text-grey-7">{{ tab === 'unassigned' ? 'Нераспределённых результатов нет' : 'Результатов пока нет' }}</div>
    <HistoryDialog v-model="historyOpen" :value="historyValue" :pet-id="historyPet" />
  </q-page>
</template>

<script setup>
// Лаборатория: все результаты с приборов и нераспределённые — с привязкой к медкарте по номеру.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'
import HistoryDialog from './HistoryDialog.vue'
import LabResultCard from './LabResultCard.vue'

const $q = useQuasar()
const tab = ref('unassigned')
const results = ref([])
const unassigned = ref(0)
const historyOpen = ref(false)
const historyValue = ref(null)
const historyPet = ref(null)

async function load() {
  const [list, count] = await Promise.all([
    apiGet(`laboratory/results/${tab.value === 'unassigned' ? '?status=unassigned' : ''}`),
    apiGet('laboratory/results/unassigned-count/'),
  ])
  results.value = list.data ?? []
  unassigned.value = count.data?.count ?? 0
  if (tab.value === 'unassigned' && !unassigned.value && results.value.length === 0) tab.value = 'unassigned'
}

function assign(result) {
  $q.dialog({
    title: 'Привязать к медкарте', message: 'Номер приёма (номер для анализатора из записи медкарты)',
    prompt: { model: result.code_entered || '', type: 'number' }, cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Привязать', color: 'primary', unelevated: true },
  }).onOk(async (code) => {
    const { ok, data } = await apiPost(`laboratory/results/${result.id}/assign/`, { lab_code: code })
    if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось привязать' })
    $q.notify({ type: 'positive', message: `Результат перенесён в медкарту: ${data.pet_name}` })
    load()
  })
}

function openHistory(value) {
  historyValue.value = value
  historyPet.value = results.value.find((r) => r.values.some((v) => v.id === value.id))?.pet
  historyOpen.value = true
}

onMounted(load)
</script>
