<template>
  <q-page padding>
    <div class="row items-center q-mb-sm q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Порядок в прайсе</h1>
      <q-btn flat round icon="refresh" :loading="loading" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
    </div>
    <p class="text-grey-8">
      В VetManager каждая фасовка — отдельная позиция. У нас это одна позиция с несколькими единицами продажи:
      «саше» — единица учёта, «упак.» — 30 саше. Проверьте предложения и объедините. Ничего не меняется, пока
      вы не нажмёте «Объединить». Делать это лучше до приходов и счетов — использованные позиции не объединяются.
    </p>

    <q-banner v-if="!loading && !rows.length" class="bg-green-1">
      <template #avatar><q-icon name="check_circle" color="positive" /></template>
      Похожих позиций не нашлось — прайс в порядке.
    </q-banner>

    <q-card v-for="row in rows" :key="row.base_name" flat bordered class="q-mb-sm">
      <q-card-section class="row items-center q-py-sm q-gutter-sm">
        <q-badge :color="row.kind === 'duplicates' ? 'orange' : 'primary'" outline
          :label="row.kind === 'duplicates' ? 'дубли' : 'фасовки'" />
        <q-input v-model="row.name" dense outlined class="col" label="Название после объединения" />
        <q-btn color="primary" unelevated icon="merge" label="Объединить" :loading="merging === row.base_name"
          :disable="!ready(row)" @click="merge(row)" />
      </q-card-section>
      <q-separator />
      <q-markup-table flat dense>
        <thead>
          <tr><th class="text-left">Позиция в прайсе</th><th class="text-left">Единица</th><th>Сколько в ней</th><th class="text-right">Цена</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="part in row.items" :key="part.id" :class="part.used ? 'text-grey-6' : ''">
            <td>{{ part.name }}</td>
            <td style="width: 140px">
              <q-select v-model="part.unit" :options="units" option-value="name" option-label="name" emit-value map-options
                dense borderless :disable="part.used" />
            </td>
            <td style="width: 150px">
              <q-input v-model="part.quantity" type="number" min="0" step="1" dense outlined :disable="part.used"
                :suffix="row.items[0]?.unit" :placeholder="part.quantity === null ? 'укажите' : ''" />
            </td>
            <td class="text-right">{{ part.price ? money(part.price) : '' }}</td>
            <td class="text-right" style="width: 170px">
              <span v-if="part.used" class="text-caption text-negative">уже используется</span>
            </td>
          </tr>
        </tbody>
      </q-markup-table>
    </q-card>

    <div v-if="error" class="text-negative q-mt-md">{{ error }}</div>
  </q-page>
</template>

<script setup>
// Объединение позиций-фасовок и дублей, перенесённых из VetManager.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { money } from '@/modules/catalog/money'

const $q = useQuasar()
const rows = ref([])
const units = ref([])
const loading = ref(false)
const merging = ref('')
const error = ref('')

// Объединять можно, когда у всех позиций указано, сколько единиц внутри.
const ready = (row) => row.items.every((part) => Number(part.quantity) > 0 && !part.used)

async function load() {
  loading.value = true
  error.value = ''
  const [found, unitList] = await Promise.all([apiGet('vetmanager/tidy/'), apiGet('catalog/units/?active=true')])
  rows.value = found.data ?? []
  units.value = unitList.data ?? []
  loading.value = false
}

async function merge(row) {
  error.value = ''
  merging.value = row.base_name
  const { ok, data } = await apiPost('vetmanager/tidy/', {
    name: row.name,
    parts: row.items.map((part) => ({ item: part.id, quantity: part.quantity, unit: part.unit })),
  })
  merging.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось объединить')
  $q.notify({ type: 'positive', message: `Объединено: ${data.name}` })
  rows.value = rows.value.filter((item) => item.base_name !== row.base_name)
}

onMounted(load)
</script>
