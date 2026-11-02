<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 640px; max-width: 96vw">
      <q-card-section class="row items-center">
        <div class="text-h6 col">{{ value?.name }}</div>
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-card-section v-if="points.length > 1" class="q-pt-none">
        <svg :viewBox="`0 0 ${W} ${H}`" style="width: 100%; height: 180px">
          <rect v-if="band" :x="PAD" :y="y(band.high)" :width="W - 2 * PAD" :height="Math.max(y(band.low) - y(band.high), 0)"
            fill="rgba(60,122,78,0.12)" />
          <polyline :points="points.map((p, i) => `${x(i)},${y(p.v)}`).join(' ')" fill="none" stroke="currentColor" stroke-width="2"
            class="text-primary" />
          <g v-for="(p, i) in points" :key="i">
            <circle :cx="x(i)" :cy="y(p.v)" r="4" :fill="p.flag === 'high' ? '#c62828' : p.flag === 'low' ? '#1565c0' : '#24566a'" />
            <text :x="x(i)" :y="y(p.v) - 8" text-anchor="middle" font-size="11" fill="currentColor">{{ p.label }}</text>
          </g>
        </svg>
        <div v-if="band" class="text-caption text-grey-7">Зелёная полоса — референс последнего анализа ({{ points[points.length - 1].ref }})</div>
      </q-card-section>
      <q-list dense separator>
        <q-item v-for="(r, i) in rows.slice().reverse()" :key="i">
          <q-item-section>{{ new Date(r.date).toLocaleDateString('ru-RU') }}</q-item-section>
          <q-item-section side :class="r.flag === 'high' ? 'text-negative' : r.flag === 'low' ? 'text-info' : ''">
            {{ r.value }} {{ r.unit }} {{ r.flag === 'high' ? '↑' : r.flag === 'low' ? '↓' : '' }}
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Динамика показателя у питомца: график с полосой нормы и список значений.
import { computed, ref, watch } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false }, value: { type: Object, default: null }, petId: { type: String, default: null } })
const emit = defineEmits(['update:modelValue'])
const rows = ref([])
const W = 600
const H = 180
const PAD = 30

watch(() => props.modelValue, async (open) => {
  if (!open || !props.value) return
  rows.value = (await apiGet(`laboratory/results/history/?pet=${props.petId}&analyte=${props.value.analyte}`)).data ?? []
}, { immediate: true })

const points = computed(() => rows.value.filter((r) => r.numeric !== null).map((r) => ({
  v: Number(r.numeric), flag: r.flag, ref: r.reference, label: Number(r.numeric).toLocaleString('ru-RU', { maximumFractionDigits: 2 }),
})))
const band = computed(() => {
  const ref_ = points.value.at(-1)?.ref || ''
  const m = ref_.match(/^\s*([\d.,]+)\s*[-–]\s*([\d.,]+)/)
  return m ? { low: Number(m[1].replace(',', '.')), high: Number(m[2].replace(',', '.')) } : null
})
const range = computed(() => {
  const vals = points.value.map((p) => p.v).concat(band.value ? [band.value.low, band.value.high] : [])
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  return { min, max: max === min ? min + 1 : max }
})
const x = (i) => PAD + (i * (W - 2 * PAD)) / Math.max(points.value.length - 1, 1)
const y = (v) => H - PAD - ((v - range.value.min) / (range.value.max - range.value.min)) * (H - 2 * PAD)
</script>
