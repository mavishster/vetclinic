<template>
  <q-card flat bordered class="q-mb-md">
    <q-card-section class="row items-center q-py-sm">
      <div class="col">
        <div class="text-subtitle1">{{ result.analysis }}</div>
        <div class="text-caption text-grey-7">
          {{ new Date(result.received_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) }} · {{ result.device }}
          <template v-if="showPet && result.pet_name"> · {{ result.pet_name }}</template>
          <template v-if="result.visit_lab_code"> · приём № {{ result.visit_lab_code }}</template>
        </div>
      </div>
      <q-badge v-if="result.abnormal" color="negative" :label="`отклонений: ${result.abnormal}`" />
      <slot name="actions" />
    </q-card-section>
    <q-markup-table flat dense wrap-cells separator="horizontal">
      <thead><tr><th class="text-left">Показатель</th><th class="text-right">Результат</th><th class="text-left">Ед.</th><th class="text-left">Референс</th><th /></tr></thead>
      <tbody>
        <tr v-for="v in result.values" :key="v.id" :class="FLAG[v.flag]?.row">
          <td>
            <a v-if="v.numeric !== null && v.analyte && result.pet" href="#" class="text-primary" @click.prevent="emit('history', v)">{{ v.name }}</a>
            <span v-else>{{ v.name }}</span>
          </td>
          <td class="text-right text-weight-medium" :class="FLAG[v.flag]?.text">{{ v.value }} {{ FLAG[v.flag]?.arrow || '' }}</td>
          <td class="text-grey-8">{{ v.unit }}</td>
          <td class="text-grey-8">{{ v.reference }}</td>
          <td class="text-caption" :class="FLAG[v.flag]?.text">{{ FLAG[v.flag]?.label || '' }}</td>
        </tr>
      </tbody>
    </q-markup-table>
  </q-card>
</template>

<script setup>
// Бланк результата: показатели с отметками ↑↓ (выше нормы — красным, ниже — синим).
// Клик по показателю — его динамика у питомца.
defineProps({ result: { type: Object, required: true }, showPet: { type: Boolean, default: false } })
const emit = defineEmits(['history'])
const FLAG = {
  high: { arrow: '↑', label: 'выше нормы', text: 'text-negative', row: '' },
  low: { arrow: '↓', label: 'ниже нормы', text: 'text-info', row: '' },
  positive: { arrow: '', label: 'положительно', text: 'text-negative', row: 'row-highlight-negative' },
}
</script>
