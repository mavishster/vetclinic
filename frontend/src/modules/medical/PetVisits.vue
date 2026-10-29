<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="text-subtitle1 col">Медкарта</div>
      <q-btn v-if="can('medical.add_visit') && pet.status === 'active'" flat dense color="primary" icon="post_add"
        label="Новая запись" :loading="creating" @click="create" />
    </q-card-section>
    <q-list separator>
      <q-item v-for="v in visits" :key="v.id" clickable :to="`/visits/${v.id}`">
        <q-item-section side class="text-weight-medium">{{ new Date(v.date).toLocaleDateString('ru-RU') }}</q-item-section>
        <q-item-section>
          <q-item-label>{{ v.purpose_name }}{{ v.diagnoses.length ? ` · ${v.diagnoses.map((d) => d.name).join(', ')}` : '' }}</q-item-label>
          <q-item-label caption>{{ v.doctor_name }}{{ v.vaccinations.length ? ` · вакцинация: ${v.vaccinations.map((x) => x.vaccine_name).join(', ')}` : '' }}</q-item-label>
        </q-item-section>
      </q-item>
      <q-item v-if="!visits.length"><q-item-section class="text-grey-7">Записей пока нет</q-item-section></q-item>
    </q-list>
  </q-card>
</template>

<script setup>
// Блок медкарты в карточке питомца (модуль «Медкарта»).
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const props = defineProps({ pet: { type: Object, required: true } })
const router = useRouter()
const $q = useQuasar()
const visits = ref([])
const creating = ref(false)

async function create() {
  creating.value = true
  const { ok, data } = await apiPost('medical/visits/', { pet: props.pet.id })
  creating.value = false
  if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось создать запись' })
  router.push(`/visits/${data.id}`)
}

onMounted(async () => {
  visits.value = (await apiGet(`medical/visits/?pet=${props.pet.id}&page_size=100`)).data?.results ?? []
})
</script>
