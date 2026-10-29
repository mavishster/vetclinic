<template>
  <q-card flat bordered>
    <q-card-section class="row items-center q-gutter-sm">
      <div class="text-subtitle1 col">Питомцы</div>
      <q-toggle v-model="showFormer" label="Бывшие" dense @update:model-value="load" />
      <q-btn v-if="can('clients.add_pet')" flat dense color="primary" icon="add" label="Добавить" @click="editorOpen = true" />
    </q-card-section>
    <q-list separator>
      <q-item v-for="pet in pets" :key="pet.id" clickable :to="`/pets/${pet.id}`">
        <q-item-section avatar><q-icon name="pets" :color="pet.status === 'dead' ? 'grey-5' : 'primary'" /></q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-medium">
            {{ pet.name }}
            <q-badge v-if="pet.status === 'dead'" color="grey-6" label="умер" class="q-ml-xs" />
          </q-item-label>
          <q-item-label caption>
            {{ [pet.species_name, pet.breed_name, sexLabel(pet).toLowerCase(), ageText(pet)].filter(Boolean).join(' · ') }}
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="pet.weight" side>{{ Number(pet.weight.weight) }} кг</q-item-section>
      </q-item>
      <q-item v-for="pet in former" :key="`former-${pet.id}`" clickable :to="`/pets/${pet.id}`" class="text-grey-6">
        <q-item-section avatar><q-icon name="pets" color="grey-5" /></q-item-section>
        <q-item-section>
          <q-item-label style="text-decoration: line-through">{{ pet.name }}</q-item-label>
          <q-item-label caption>передан: {{ pet.owner_name }}</q-item-label>
        </q-item-section>
      </q-item>
      <q-item v-if="!pets.length && !former.length">
        <q-item-section class="text-grey-7">Питомцев нет. Без питомца нельзя будет создать медкарту и счёт.</q-item-section>
      </q-item>
    </q-list>
    <PetEditDialog v-model="editorOpen" :owner-id="client.id" :owner-name="client.full_name" @saved="load" />
  </q-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api'
import { can } from '@/session'
import PetEditDialog from './PetEditDialog.vue'
import { ageText, sexLabel } from './pets'

const props = defineProps({ client: { type: Object, required: true } })
const pets = ref([])
const former = ref([])
const showFormer = ref(false)
const editorOpen = ref(false)

async function load() {
  const status = showFormer.value ? '' : '&status=active'
  const [current, past] = await Promise.all([
    apiGet(`clients/pets/?owner=${props.client.id}${status}&page_size=100`),
    showFormer.value ? apiGet(`clients/pets/?former_of=${props.client.id}&page_size=100`) : Promise.resolve({ data: { results: [] } }),
  ])
  pets.value = current.data?.results ?? []
  former.value = past.data?.results ?? []
}

onMounted(load)
</script>
