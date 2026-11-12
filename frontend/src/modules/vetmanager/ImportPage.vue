<template>
  <q-page padding>
    <h1 class="text-h5 q-mt-none">Перенос из VetManager</h1>
    <p class="text-grey-8">
      Данные забираются из VetManager по его API — только чтение, в VetManager ничего не меняется.
      Шаги выполняются по порядку; повторный запуск ничего не задваивает — переносится только новое.
    </p>

    <q-banner v-if="status && !status.configured" class="banner-warning q-mb-md">
      <template #avatar><q-icon name="warning" color="warning" /></template>
      Не заданы адрес и ключ VetManager. Добавьте в файл <code>.env</code> строки
      <code>VETMANAGER_URL</code> и <code>VETMANAGER_API_KEY</code> и перезапустите систему.
    </q-banner>

    <q-list bordered separator class="rounded-borders">
      <q-item v-for="(step, index) in steps" :key="step.step">
        <q-item-section avatar>
          <q-avatar :color="step.imported ? 'positive' : 'grey-4'" :text-color="step.imported ? 'white' : 'grey-8'" size="32px">
            {{ index + 1 }}
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-medium">{{ step.title }}</q-item-label>
          <q-item-label caption>
            {{ step.imported ? `перенесено: ${step.detail || step.imported}` : 'ещё не переносили' }}
            <span v-if="results[step.step]"> · {{ results[step.step].text }}</span>
          </q-item-label>
          <q-item-label v-if="results[step.step]?.errors?.length" caption class="text-negative">
            {{ results[step.step].errors.join('; ') }}
          </q-item-label>
        </q-item-section>
        <q-item-section side class="row items-center no-wrap q-gutter-sm">
          <q-btn v-if="step.step === 'units'" flat color="primary" label="Как сведутся" :loading="planning"
            :disable="!status?.configured || !!running" @click="showUnitPlan" />
          <q-btn :color="step.imported ? 'grey-7' : 'primary'" :outline="!!step.imported" unelevated
            :label="step.imported ? 'Перенести ещё раз' : 'Перенести'" :loading="running === step.step"
            :disable="!status?.configured || !!running" @click="run(step)" />
        </q-item-section>
      </q-item>
    </q-list>

    <div v-if="error" class="text-negative q-mt-md">{{ error }}</div>

    <q-expansion-item class="q-mt-lg" icon="search" label="Что отдаёт VetManager" caption="Проверить связь и поля — перед переносом">
      <div class="row q-col-gutter-sm q-pa-sm items-center">
        <q-select v-model="probeModel" :options="MODELS" outlined dense use-input new-value-mode="add-unique" class="col-6 col-md-3"
          label="Раздел VetManager" @new-value="(v, done) => done(v)" />
        <q-btn outline color="primary" label="Посмотреть" :loading="probing" :disable="!status?.configured" @click="probe" />
      </div>
      <div v-if="probeResult" class="q-pa-sm">
        <div>Записей: <b>{{ probeResult.total }}</b></div>
        <div class="q-mt-xs">Поля: {{ probeResult.fields.join(', ') || '—' }}</div>
        <pre class="sample q-mt-sm">{{ JSON.stringify(probeResult.rows, null, 1) }}</pre>
      </div>
    </q-expansion-item>
  </q-page>
</template>

<script setup>
// Перенос из VetManager по шагам: справочники → товары и услуги (дальше — клиенты, питомцы,
// медкарты, счета). «Что отдаёт VetManager» показывает поля реального аккаунта.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'

const MODELS = ['Unit', 'GoodGroup', 'Good', 'GoodSaleParam', 'Client', 'Pet', 'PetType', 'Breed', 'Admission', 'Invoice']
const $q = useQuasar()
const status = ref(null)
const steps = ref([])
const results = ref({})
const running = ref('')
const error = ref('')
const probeModel = ref('Good')
const probeResult = ref(null)
const probing = ref(false)
const planning = ref(false)

async function load() {
  const { ok, data } = await apiGet('vetmanager/status/')
  if (!ok) return
  status.value = data
  steps.value = data.steps
}

async function run(step) {
  error.value = ''
  running.value = step.step
  const { ok, data } = await apiPost('vetmanager/run/', { step: step.step })
  running.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось перенести')
  results.value = { ...results.value, [step.step]: data }
  $q.notify({ type: data.errors?.length ? 'warning' : 'positive', message: `${data.title}: ${data.text}` })
  load()
}

// В VetManager единицы часто задвоены («шт», «шт.», «штука») — показываем, что с чем сведётся.
async function showUnitPlan() {
  error.value = ''
  planning.value = true
  const { ok, data } = await apiGet('vetmanager/unit-plan/')
  planning.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось получить список')
  const rows = data.map((row) => {
    const from = row.sources.join(', ')
    const mark = row.is_new ? ' <b>(новая)</b>' : ''
    return `• ${from} → <b>${row.target}</b>${mark}`
  })
  $q.dialog({
    title: 'Единицы измерения',
    message: rows.length
      ? `Переносятся только те, что используются в товарах и ценах:<br>${rows.join('<br>')}`
      : 'В VetManager не нашлось единиц измерения.',
    html: true,
    ok: { label: 'Понятно', color: 'primary', flat: true },
  })
}

async function probe() {
  error.value = ''
  probing.value = true
  probeResult.value = null
  const { ok, data } = await apiGet(`vetmanager/probe/?model=${encodeURIComponent(probeModel.value)}`)
  probing.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось получить данные')
  probeResult.value = data
}

onMounted(load)
</script>

<style scoped>
.sample {
  background: rgba(127, 127, 127, 0.1);
  padding: 8px;
  border-radius: 6px;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
