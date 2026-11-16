<template>
  <q-page padding>
    <div class="row items-center q-mb-sm q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Порядок в прайсе</h1>
      <q-btn flat round icon="refresh" :loading="loading" @click="load"><q-tooltip>Обновить</q-tooltip></q-btn>
    </div>
    <q-tabs v-model="tab" dense align="left" class="q-mb-md" active-color="primary" indicator-color="primary">
      <q-tab name="packaging" :label="`Фасовки препаратов${packaging.length ? ` (${packaging.length})` : ''}`" />
      <q-tab name="pairs" :label="`Дубли и пары${rows.length ? ` (${rows.length})` : ''}`" />
    </q-tabs>

    <template v-if="tab === 'packaging'">
      <p class="text-grey-8">
        Здесь препараты, у которых остаток ведётся упаковками, а отпускают поштучно: продажа
        2 мл списала бы целый флакон. Укажите, сколько внутри, — остаток станет вестись в мелкой
        единице, а упаковка останется единицей закупки: приход по-прежнему оформляется упаковками.
      </p>
      <q-banner v-if="!loading && !packaging.length" class="banner-positive q-mb-md">
        <template #avatar><q-icon name="check_circle" color="positive" /></template>
        Препаратов с таким расхождением не нашлось.
      </q-banner>
      <q-markup-table v-else flat bordered dense class="q-mb-lg">
        <thead>
          <tr>
            <th class="text-left">Препарат</th>
            <th class="text-left">Сейчас учёт в</th>
            <th>В упаковке</th>
            <th class="text-left">Чего</th>
            <th class="text-right">Цена за единицу</th>
            <th class="text-right">В счетах</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in packaging" :key="row.id" :class="row.used ? 'text-grey-6' : ''">
            <td>{{ row.name }}</td>
            <td>{{ row.base_unit }}</td>
            <td style="width: 130px">
              <q-input v-model="row.quantity" type="number" min="2" dense outlined :disable="row.used"
                :placeholder="row.quantity === null ? 'укажите' : ''" />
            </td>
            <td style="width: 130px">
              <q-select v-model="row.inside" :options="units" option-value="name" option-label="name"
                emit-value map-options dense outlined :disable="row.used" />
            </td>
            <td style="width: 140px">
              <q-input v-model="row.price" type="number" min="0" dense outlined :disable="row.used"
                placeholder="необязательно" />
            </td>
            <td class="text-right text-grey-7">{{ row.documents || '' }}</td>
            <td class="text-right" style="width: 150px">
              <span v-if="row.used" class="text-caption text-negative">уже используется</span>
              <template v-else>
                <q-btn color="primary" unelevated dense label="Поправить" :loading="fixing === row.id"
                  :disable="!(Number(row.quantity) > 1 && row.inside)" @click="fixPackaging(row)" />
                <q-btn flat dense color="grey-7" icon="check" :loading="fixing === row.id"
                  @click="skipPackaging(row)">
                  <q-tooltip>Не трогать: позиция и так в порядке</q-tooltip>
                </q-btn>
              </template>
            </td>
          </tr>
        </tbody>
      </q-markup-table>
    </template>

    <template v-else>
    <p class="text-grey-8">
      В VetManager каждая фасовка — отдельная позиция. У нас это одна позиция с несколькими единицами продажи:
      «саше» — единица учёта, «упак.» — 30 саше. Проверьте предложения и объедините. Ничего не меняется, пока
      вы не нажмёте «Объединить». Делать это лучше до приходов и счетов — использованные позиции не объединяются.
    </p>

    <q-banner v-if="!loading && !rows.length" class="banner-positive">
      <template #avatar><q-icon name="check_circle" color="positive" /></template>
      Похожих позиций не нашлось — прайс в порядке.
    </q-banner>

    <q-card v-for="row in rows" :key="row.base_name" flat bordered class="q-mb-sm">
      <q-card-section class="row items-center q-py-sm q-gutter-sm">
        <q-badge :color="row.kind === 'duplicates' ? 'orange' : 'primary'" outline
          :label="row.kind === 'duplicates' ? 'дубли' : 'фасовки'" />
        <q-badge v-if="row.documents" color="grey-7" outline :label="`в счетах: ${row.documents}`">
          <q-tooltip>Сколько раз позиции встречаются в счетах VetManager</q-tooltip>
        </q-badge>
        <q-input v-model="row.name" dense outlined class="col" label="Название после объединения" />
        <q-btn color="primary" unelevated icon="merge" label="Объединить" :loading="merging === row.base_name"
          :disable="!ready(row)" @click="merge(row)" />
        <q-btn flat color="grey-7" label="Не объединять" :loading="merging === row.base_name" @click="skipPair(row)">
          <q-tooltip>Это разные товары — размеры, модели</q-tooltip>
        </q-btn>
      </q-card-section>
      <q-separator />
      <q-markup-table flat dense>
        <thead>
          <tr><th class="text-left">Позиция в прайсе</th><th class="text-left">Единица</th><th>Сколько в ней</th><th class="text-right">Цена</th><th class="text-right">В счетах</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="part in row.items" :key="part.id" :class="part.used ? 'text-grey-6' : ''">
            <td>{{ part.name }}</td>
            <td style="width: 140px">
              <q-select v-model="part.unit" :options="units" option-value="name" option-label="name" emit-value map-options
                dense borderless use-input new-value-mode="add-unique" :disable="part.used"
                @new-value="(value, done) => done(value)" />
            </td>
            <td style="width: 150px">
              <q-input v-model="part.quantity" type="number" min="0" step="1" dense outlined :disable="part.used"
                :suffix="row.items[0]?.unit" :placeholder="part.quantity === null ? 'укажите' : ''" />
            </td>
            <td class="text-right">{{ part.price ? money(part.price) : '' }}</td>
            <td class="text-right text-grey-7">{{ part.documents || '' }}</td>
            <td class="text-right" style="width: 170px">
              <span v-if="part.used" class="text-caption text-negative">уже используется</span>
            </td>
          </tr>
        </tbody>
      </q-markup-table>
    </q-card>

    </template>

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
const tab = ref('packaging')
const rows = ref([])
const packaging = ref([])
const fixing = ref('')
const units = ref([])
const loading = ref(false)
const merging = ref('')
const error = ref('')

// Объединять можно, когда у всех позиций указано, сколько единиц внутри.
const ready = (row) => row.items.every((part) => Number(part.quantity) > 0 && !part.used)

async function load() {
  loading.value = true
  error.value = ''
  const [found, unitList, packs] = await Promise.all([
    apiGet('vetmanager/tidy/'),
    apiGet('catalog/units/?active=true'),
    apiGet('vetmanager/packaging/'),
  ])
  rows.value = found.data ?? []
  units.value = unitList.data ?? []
  packaging.value = packs.data ?? []
  loading.value = false
}

// Остаток переводим в мелкую единицу, упаковку оставляем единицей закупки.
async function fixPackaging(row) {
  error.value = ''
  fixing.value = row.id
  const { ok, data } = await apiPost('vetmanager/packaging/', {
    item: row.id, quantity: row.quantity, inside: row.inside, price: row.price || null,
  })
  fixing.value = ''
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось поправить')
  $q.notify({ type: 'positive', message: `${data.name}: учёт в «${data.base_unit}»` })
  packaging.value = packaging.value.filter((item) => item.id !== row.id)
}

// «Не трогать»: позиция продаётся целиком (набор, флакон без отлива) — убираем из списка.
async function skipPackaging(row) {
  fixing.value = row.id
  const { ok } = await apiPost('vetmanager/packaging/', { item: row.id, skip: true })
  fixing.value = ''
  if (ok) packaging.value = packaging.value.filter((item) => item.id !== row.id)
}

// «Не объединять»: «Воротник №5» и «№8» — разные размеры, а не фасовки одного товара.
async function skipPair(row) {
  merging.value = row.base_name
  const { ok } = await apiPost('vetmanager/tidy/', { skip: true, base_name: row.base_name })
  merging.value = ''
  if (ok) rows.value = rows.value.filter((item) => item.base_name !== row.base_name)
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
