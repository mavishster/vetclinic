<template>
  <q-select :model-value="modelValue" :options="options" option-value="id" option-label="label" emit-value
    map-options use-input input-debounce="300" outlined :label="label" :hint="hint" @filter="search"
    @update:model-value="emit('update:modelValue', $event)">
    <template #no-option>
      <q-item><q-item-section class="text-grey-7">Начните вводить фамилию или телефон</q-item-section></q-item>
    </template>
  </q-select>
</template>

<script setup>
// Выбор клиента с поиском по фамилии, телефону, кличке питомца (поиск идёт на сервере).
import { ref } from 'vue'
import { apiGet } from '@/api'

defineProps({
  modelValue: { type: String, default: null },
  label: { type: String, default: 'Клиент' },
  hint: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
const options = ref([])

async function search(text, update, abort) {
  if (text.trim().length < 2) {
    update(() => (options.value = []))
    return
  }
  const { ok, data } = await apiGet(`clients/clients/?page_size=20&search=${encodeURIComponent(text)}`)
  if (!ok) return abort()
  update(() => {
    options.value = data.results.map((c) => ({
      id: c.id,
      label: [c.full_name, c.phones[0]?.number].filter(Boolean).join(' · '),
    }))
  })
}
</script>
