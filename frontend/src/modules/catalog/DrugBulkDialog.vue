<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">Вещество и группа для {{ items.length }} позиций</q-card-section>
      <q-card-section class="q-pt-none q-gutter-md">
        <q-select v-model="substances" :options="substanceOptions" option-value="id" :option-label="substanceLabel" emit-value
          map-options multiple use-chips use-input input-debounce="200" outlined dense label="Действующие вещества"
          @filter="filterSubstances">
          <template #no-option><q-item><q-item-section class="text-grey-7">Не найдено. Новое вещество заводится в карточке товара или в справочнике</q-item-section></q-item></template>
        </q-select>
        <q-select v-model="groups" :options="groupOptions" option-value="id" option-label="name" emit-value
          map-options multiple use-chips use-input input-debounce="200" outlined dense label="Группы препарата"
          hint="Не указывать — подставятся по веществам" @filter="filterGroups" />
        <q-option-group v-model="mode" :options="MODES" dense />
        <div class="text-caption text-grey-7">{{ names }}</div>
        <div v-if="error" class="text-negative">{{ error }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup />
        <q-btn color="primary" unelevated icon="save" label="Проставить" :loading="saving" :disable="!substances.length && !groups.length" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Проставить действующие вещества и группы сразу нескольким позициям прайса.
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost, fieldErrors } from '@/api'

const MODES = [
  { label: 'Добавить к уже указанным', value: 'add' },
  { label: 'Заменить целиком', value: 'replace' },
]
const props = defineProps({ modelValue: Boolean, items: { type: Array, default: () => [] } })
const emit = defineEmits(['update:modelValue', 'saved'])
const $q = useQuasar()
const allSubstances = ref([])
const allGroups = ref([])
const substanceOptions = ref([])
const groupOptions = ref([])
const substances = ref([])
const groups = ref([])
const mode = ref('add')
const saving = ref(false)
const error = ref('')
const substanceLabel = (s) => (s.latin_name ? `${s.name} · ${s.latin_name}` : s.name)
const names = computed(() => props.items.slice(0, 5).map((i) => i.name).join(', ') + (props.items.length > 5 ? ` и ещё ${props.items.length - 5}` : ''))
const matches = (option, text) => [option.name, option.latin_name, option.synonyms].some((v) => (v || '').toLowerCase().includes(text))

function filterSubstances(text, update) {
  const needle = text.toLowerCase()
  update(() => (substanceOptions.value = needle ? allSubstances.value.filter((o) => matches(o, needle)) : allSubstances.value))
}
function filterGroups(text, update) {
  const needle = text.toLowerCase()
  update(() => (groupOptions.value = needle ? allGroups.value.filter((o) => matches(o, needle)) : allGroups.value))
}

watch(() => props.modelValue, async (open) => {
  if (!open) return
  error.value = ''
  substances.value = []
  groups.value = []
  mode.value = 'add'
  const [subs, dgroups] = await Promise.all([apiGet('catalog/substances/?active=true'), apiGet('catalog/drug-groups/?active=true')])
  allSubstances.value = subs.data ?? []
  allGroups.value = dgroups.data ?? []
  substanceOptions.value = allSubstances.value
  groupOptions.value = allGroups.value
})

async function save() {
  saving.value = true
  const { ok, data } = await apiPost('catalog/items/set-drug-info/', {
    items: props.items.map((i) => i.id), substances: substances.value, drug_groups: groups.value, replace: mode.value === 'replace',
  })
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data || {}))[0] || 'Не удалось проставить')
  $q.notify({ type: 'positive', message: `Проставлено: ${data.updated} поз.` })
  emit('saved')
  emit('update:modelValue', false)
}
</script>
