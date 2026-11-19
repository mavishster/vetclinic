<template>
  <!-- Сверка переноса: ничего ли не потерялось. Считаем записи с обеих сторон. -->
  <div>
    <div class="row items-center q-mb-md">
      <q-btn color="primary" unelevated icon="fact_check" label="Сверить" :loading="loading" @click="load" />
      <q-space />
      <div v-if="rows.length" class="text-h6" :class="allOk ? 'text-positive' : 'text-warning'">
        {{ allOk ? 'Сошлось' : summary }}
      </div>
    </div>

    <p class="text-grey-8">
      Сколько записей в VetManager и сколько доехало к нам. Расхождение — это не всегда потеря:
      задвоенные единицы сводятся, удалённые записи не переносятся. Щёлкните по строке, чтобы
      увидеть, чего именно не хватает.
    </p>

    <q-markup-table v-if="rows.length" flat bordered>
      <thead>
        <tr>
          <th class="text-left">Раздел</th>
          <th class="text-right">В VetManager</th>
          <th class="text-right">У нас</th>
          <th class="text-left">Расхождение</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.key">
          <tr :class="row.ok ? '' : 'row-highlight-warning'">
            <td>{{ row.title }}</td>
            <td class="text-right">{{ row.error ? '—' : row.theirs }}</td>
            <td class="text-right">{{ row.error ? '—' : row.ours }}</td>
            <td>
              <span v-if="row.error" class="text-negative">{{ row.error }}</span>
              <span v-else-if="row.ok" class="text-positive">сошлось</span>
              <span v-else>{{ row.note || `не хватает ${row.theirs - row.ours}` }}</span>
            </td>
            <td class="text-right" style="width: 120px">
              <q-btn v-if="row.missing?.length" flat dense size="sm"
                :icon="open[row.key] ? 'expand_less' : 'expand_more'"
                :label="String(row.missing.length)" @click="open[row.key] = !open[row.key]" />
            </td>
          </tr>
          <tr v-if="open[row.key]" :key="`${row.key}-detail`">
            <td colspan="5" class="q-pa-none">
              <q-list dense separator>
                <q-item v-for="miss in row.missing.slice(0, 100)" :key="miss.id">
                  <q-item-section>
                    <q-item-label>{{ miss.name || `№ ${miss.id}` }}</q-item-label>
                    <q-item-label caption>
                      {{ miss.reason }}<template v-if="miss.lines"> · строк в счетах: {{ miss.lines }}</template>
                    </q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-if="row.missing.length > 100">
                  <q-item-section class="text-grey-7">
                    и ещё {{ row.missing.length - 100 }}
                  </q-item-section>
                </q-item>
              </q-list>
            </td>
          </tr>
        </template>
      </tbody>
    </q-markup-table>

    <div v-if="error" class="text-negative q-mt-md">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { apiGet, fieldErrors } from '@/api'

const rows = ref([])
const open = reactive({})
const loading = ref(false)
const error = ref('')

const allOk = computed(() => rows.value.length && rows.value.every((row) => row.ok))
const summary = computed(() => {
  const bad = rows.value.filter((row) => !row.ok)
  const lost = bad.reduce((sum, row) => sum + (row.missing?.length || 0), 0)
  return `Расхождение: ${bad.length} ${bad.length === 1 ? 'раздел' : 'разделов'}${lost ? `, записей: ${lost}` : ''}`
})

// Сверка идёт к VetManager за всеми разделами — это небыстро, поэтому по кнопке.
async function load() {
  error.value = ''
  loading.value = true
  const { ok, data } = await apiGet('vetmanager/reconcile/')
  loading.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось сверить')
  rows.value = data ?? []
}
</script>
