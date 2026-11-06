<template>
  <q-btn v-if="alerts.length" flat round icon="domain" :color="urgent ? 'red-3' : undefined">
    <q-badge floating :color="urgent ? 'negative' : 'warning'" :label="alerts.length" />
    <q-tooltip>Отделения: остатки, выдача, нормы</q-tooltip>
    <q-menu anchor="bottom right" self="top right" style="min-width: 340px; max-width: 95vw">
      <q-list dense>
        <q-item-label header>Отделения — требуют внимания</q-item-label>
        <q-item v-for="a in alerts" :key="a.department + a.kind" clickable v-close-popup
          @click="$router.push({ path: '/inventory/departments', query: { department: a.department } })">
          <q-item-section avatar><q-icon :name="a.level === 'negative' ? 'error' : 'warning'" :color="a.level === 'negative' ? 'negative' : 'warning'" /></q-item-section>
          <q-item-section>
            <q-item-label class="text-weight-medium">{{ a.department_name }}</q-item-label>
            <q-item-label caption>{{ a.message }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup>
// Предупреждения по отделениям (сроки — в настройках клиники): остатки не внесены после выдачи,
// давно не было выдачи, материалы ниже нормы. Видят главный администратор (особое право
// «Отделения: нормы, контроль…») — все отделения, ответственный за отделение — свои.
// Кнопка появляется, только когда есть предупреждения; проверка — раз в 5 минут.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiGet } from '@/api'

const alerts = ref([])
const urgent = computed(() => alerts.value.some((a) => a.level === 'negative'))
let timer = null

async function load() {
  const { ok, data } = await apiGet('inventory/department-stock/alerts/')
  if (ok) alerts.value = data
}

onMounted(() => {
  load()
  timer = setInterval(load, 5 * 60000)
  window.addEventListener('departments-changed', load) // после выдачи, пересчёта, нормы — сразу
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('departments-changed', load)
})
</script>
