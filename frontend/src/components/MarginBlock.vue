<template>
  <!-- Прибыль: видна только сотрудникам с правом «Видеть себестоимость». В печать не идёт. -->
  <div v-if="margin" class="margin-block text-caption q-mt-xs" :class="dense ? '' : 'q-pa-sm rounded-borders'">
    <span>Себестоимость: {{ money(margin.cost) }}</span>
    <span class="q-ml-sm">Прибыль: <b :class="Number(margin.profit) < 0 ? 'text-negative' : 'text-positive'">{{ money(margin.profit) }}</b></span>
    <span v-if="margin.margin !== null" class="q-ml-sm text-grey-7">({{ percent(margin.margin) }} %)</span>
    <q-icon v-if="margin.unknown_cost" name="info" color="warning" size="16px" class="q-ml-xs">
      <q-tooltip>У {{ margin.unknown_cost }} поз. себестоимость не указана — прибыль показана завышенной</q-tooltip>
    </q-icon>
  </div>
</template>

<script setup>
import { money } from '@/modules/catalog/money'

defineProps({ margin: { type: Object, default: null }, dense: Boolean })

// Проценты по-русски: 58,3 — как и остальные числа в системе.
const percent = (value) => Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 1 })
</script>

<style scoped>
.margin-block {
  background: rgba(127, 127, 127, 0.08);
  display: inline-block;
}
</style>
