<template>
  <q-card flat bordered>
    <q-card-section class="text-subtitle1">Профилактика</q-card-section>
    <q-list dense separator>
      <q-item v-for="(row, i) in rows" :key="i" :clickable="!!row.last" :to="row.last ? `/visits/${row.last.visit}` : undefined">
        <q-item-section>
          <q-item-label>{{ row.type }}<span v-if="row.last?.item" class="text-grey-8"> · {{ row.last.item }}</span></q-item-label>
          <q-item-label caption>
            <template v-if="row.last">{{ row.kind === 'sterilization' ? 'проведена' : 'последняя' }} {{ fmt(row.last.date) }}{{ row.last.note ? ` · ${row.last.note}` : '' }}</template>
            <template v-else>не проводилась</template>
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="row.next_date" side>
          <q-badge :color="row.overdue ? 'negative' : 'primary'" :label="`${row.overdue ? 'просрочено' : 'след.'} ${fmt(row.next_date)}`" />
        </q-item-section>
      </q-item>
      <q-item v-if="!rows.length"><q-item-section class="text-grey-7">Нет данных</q-item-section></q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// Сводка профилактики в карточке питомца (модуль «Медкарта»).
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({ pet: { type: Object, required: true } })
const rows = ref([])
const fmt = (iso) => new Date(iso).toLocaleDateString('ru-RU')
onMounted(async () => {
  rows.value = (await apiGet(`medical/preventions/summary/?pet=${props.pet.id}`)).data ?? []
})
</script>
