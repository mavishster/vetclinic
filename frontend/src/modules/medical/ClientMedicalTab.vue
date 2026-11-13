<template>
  <!-- Медкарта клиента на одном экране: слева питомцы, справа история приёмов.
       Запись раскрывается на месте — без перехода на отдельный экран. -->
  <div class="row q-col-gutter-md">
    <div class="col-12 col-md-3">
      <q-card flat bordered>
        <q-list separator>
          <q-item clickable :active="selected === 'all'" active-class="row-highlight-primary" @click="select('all')">
            <q-item-section avatar><q-icon name="pets" /></q-item-section>
            <q-item-section>
              <q-item-label>Все питомцы</q-item-label>
              <q-item-label caption>{{ pets.length }} шт. · приёмов {{ total }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-for="pet in pets" :key="pet.id" clickable :active="selected === pet.id"
            active-class="row-highlight-primary" @click="select(pet.id)">
            <q-item-section avatar>
              <q-icon name="pets" :color="pet.status === 'active' ? 'primary' : 'grey-5'" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ pet.name }}</q-item-label>
              <q-item-label caption>
                {{ [pet.species_name, pet.breed_name].filter(Boolean).join(' · ') }}
                <template v-if="counts[pet.id]"> · приёмов {{ counts[pet.id] }}</template>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </div>

    <div class="col-12 col-md-9">
      <div class="row q-col-gutter-sm q-mb-sm items-center">
        <q-input v-model="search" dense outlined clearable debounce="300" placeholder="Поиск по тексту приёма"
          class="col-12 col-md-5" @update:model-value="load">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-select v-model="doctor" :options="doctors" option-value="id" option-label="name" emit-value map-options
          dense outlined clearable label="Врач" class="col-6 col-md-3" @update:model-value="load" />
        <q-space />
        <q-btn flat dense :icon="allOpen ? 'unfold_less' : 'unfold_more'" :label="allOpen ? 'Свернуть все' : 'Развернуть все'"
          @click="toggleAll" />
      </div>

      <q-card v-for="visit in visits" :key="visit.id" flat bordered class="q-mb-sm">
        <q-card-section class="row items-center q-py-sm cursor-pointer" @click="toggle(visit.id)">
          <div class="col-auto text-weight-medium" style="min-width: 130px">
            {{ new Date(visit.date).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) }}
          </div>
          <div class="col">
            <div>
              <span v-if="selected === 'all'" class="text-weight-medium">{{ visit.pet_name }} · </span>
              {{ visit.purpose_name }}
              <span v-if="visit.diagnoses.length" class="text-grey-8">
                · {{ visit.diagnoses.map((d) => d.name).join(', ') }}
              </span>
            </div>
            <div class="text-caption text-grey-7">
              {{ visit.doctor_name }}
              <template v-if="visit.weight"> · {{ Number(visit.weight) }} кг</template>
              <template v-if="visit.temperature"> · {{ Number(visit.temperature) }} °C</template>
            </div>
          </div>
          <q-btn flat dense round :icon="open[visit.id] ? 'expand_less' : 'expand_more'" @click.stop="toggle(visit.id)" />
          <q-btn flat dense round icon="open_in_new" :to="`/visits/${visit.id}`" @click.stop>
            <q-tooltip>Открыть приём</q-tooltip>
          </q-btn>
        </q-card-section>

        <q-slide-transition>
          <div v-show="open[visit.id]">
            <q-separator />
            <q-card-section class="q-pt-sm">
              <div v-if="visit.treatment_html" class="text-body2 visit-text" v-html="visit.treatment_html" />
              <div v-else class="text-grey-7">Описание лечения не заполнено</div>
              <template v-if="visit.recommendations_html">
                <div class="text-subtitle2 q-mt-md">Рекомендации</div>
                <div class="text-body2 visit-text" v-html="visit.recommendations_html" />
              </template>
              <template v-if="visit.prescriptions?.length">
                <div class="text-subtitle2 q-mt-md">Назначения</div>
                <div v-for="row in visit.prescriptions" :key="row.id" class="text-body2">
                  {{ row.drug_name }}<span v-if="row.dose"> — {{ row.dose }}</span>
                  <span v-if="row.schedule" class="text-grey-7"> · {{ row.schedule }}</span>
                </div>
              </template>
              <template v-if="visit.preventions?.length">
                <div class="text-subtitle2 q-mt-md">Профилактика</div>
                <div v-for="row in visit.preventions" :key="row.id" class="text-body2">
                  {{ row.item_name || row.type_name }}
                  <span v-if="row.next_date" class="text-grey-7"> · следующая {{ formatDate(row.next_date) }}</span>
                </div>
              </template>
            </q-card-section>
          </div>
        </q-slide-transition>
      </q-card>

      <q-card v-if="!visits.length && !loading" flat bordered>
        <q-card-section class="text-grey-7">Приёмов пока нет</q-card-section>
      </q-card>
      <div v-if="hasMore" class="text-center q-mt-sm">
        <q-btn flat color="primary" label="Показать ещё" :loading="loading" @click="load(true)" />
      </div>
    </div>
  </div>
</template>

<script setup>
// История приёмов всех питомцев клиента: в VetManager это требовало ухода в отдельный
// экран на каждую запись — здесь всё раскрывается на месте.
import { onMounted, reactive, ref } from 'vue'
import { apiGet } from '@/api'

const props = defineProps({ client: { type: Object, required: true } })
const PAGE = 20
const pets = ref([])
const visits = ref([])
const counts = reactive({})
const open = reactive({})
const doctors = ref([])
const selected = ref('all')
const search = ref('')
const doctor = ref(null)
const loading = ref(false)
const total = ref(0)
const hasMore = ref(false)
const allOpen = ref(false)
const formatDate = (value) => (value ? new Date(value).toLocaleDateString('ru-RU') : '')

function select(value) {
  selected.value = value
  load()
}

function toggle(id) {
  open[id] = !open[id]
}

function toggleAll() {
  allOpen.value = !allOpen.value
  for (const visit of visits.value) open[visit.id] = allOpen.value
}

async function load(more = false) {
  loading.value = true
  const params = new URLSearchParams({ client: props.client.id, page_size: String(PAGE) })
  params.set('page', String(more ? Math.floor(visits.value.length / PAGE) + 1 : 1))
  if (selected.value !== 'all') params.set('pet', selected.value)
  if (search.value) params.set('search', search.value)
  if (doctor.value) params.set('doctor', doctor.value)
  const { ok, data } = await apiGet(`medical/visits/?${params}`)
  loading.value = false
  if (!ok) return
  const rows = data.results ?? data ?? []
  visits.value = more ? [...visits.value, ...rows] : rows
  total.value = data.count ?? visits.value.length
  hasMore.value = visits.value.length < (data.count ?? visits.value.length)
  // Единственный приём разворачиваем сразу — обычно его и смотрят.
  if (!more && rows.length === 1) open[rows[0].id] = true
}

onMounted(async () => {
  const [petList, doctorList] = await Promise.all([
    apiGet(`clients/pets/?owner=${props.client.id}&page_size=100`),
    apiGet('staff/employees/?in_schedule=true'),
  ])
  pets.value = petList.data?.results ?? petList.data ?? []
  doctors.value = (doctorList.data?.results ?? doctorList.data ?? []).map((e) => ({
    id: e.user ?? e.id,
    name: e.full_name || e.name,
  }))
  await load()
  // Сколько приёмов у каждого питомца — чтобы было видно, к кому заглядывать.
  for (const pet of pets.value) {
    const { data } = await apiGet(`medical/visits/?pet=${pet.id}&page_size=1`)
    counts[pet.id] = data?.count ?? 0
  }
})
</script>

<style scoped>
.visit-text :deep(p) {
  margin: 0 0 6px;
}
</style>
