<template>
  <!-- Строка подбора препарата: заголовок раздела («аналоги», «та же группа») и сама позиция. -->
  <div>
    <q-item-label v-if="header" header class="text-caption text-weight-medium q-py-xs">{{ header }}</q-item-label>
    <q-item v-bind="itemProps" :class="{ 'text-grey-7': option.stock !== null && option.stock !== undefined && Number(option.stock) <= 0 }">
      <q-item-section>
        <q-item-label>{{ option.name }}<span v-if="option.unit" class="text-grey-7"> — {{ option.unit }}</span></q-item-label>
        <q-item-label caption>
          <span v-if="option.price">{{ money(option.price) }}</span>
          <span v-else-if="option.price === null && option.item_unit">цена по закупке</span>
          <template v-if="option.stock !== null && option.stock !== undefined">
            · {{ Number(option.stock) > 0 ? `на складе ${option.stock_text || Number(option.stock)}` : 'нет в наличии' }}
          </template>
          <template v-if="option.section_note"> · {{ option.section_note }}</template>
        </q-item-label>
      </q-item-section>
    </q-item>
  </div>
</template>

<script setup>
import { money } from '@/modules/catalog/money'

defineProps({
  option: { type: Object, required: true },
  itemProps: { type: Object, default: () => ({}) },
  header: { type: String, default: '' },
})
</script>
