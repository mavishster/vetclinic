<template>
  <div>
    <q-form v-if="canEdit" class="q-gutter-y-sm q-mb-md" @submit="add">
      <div class="row q-col-gutter-sm">
        <q-select v-model="form.type" :options="types" option-value="id" option-label="name" emit-value map-options
          outlined dense label="Процедура" class="col-12 col-sm-5" @update:model-value="onType" />
        <q-select v-model="form.item" :options="preparations" option-value="id" option-label="name" emit-value map-options
          outlined dense clearable :label="isVaccination ? 'Вакцина' : 'Препарат или услуга'" class="col-12 col-sm-5"
          :hint="preparations.length ? '' : 'Отметьте в каталоге у группы или позиции вид профилактики'" />
        <q-input v-model="form.quantity" type="number" step="0.001" min="0" outlined dense label="Кол-во" class="col-12 col-sm-2" />
      </div>
      <div v-if="!oneTime" class="row q-col-gutter-sm items-center">
        <q-select v-if="isVaccination" v-model="form.stage" :options="STAGES" emit-value map-options outlined dense
          label="Этап" class="col-12 col-sm-3" />
        <q-input v-model="form.next_date" type="date" outlined dense stack-label label="Следующая" class="col-12 col-sm-4"
          :hint="selectedType?.repeat_days ? `По умолчанию — через ${selectedType.repeat_days} дн.` : ''" />
        <div class="col-12 col-sm-5 q-gutter-x-xs">
          <q-btn v-for="p in PERIODS" :key="p.label" outline dense no-caps size="sm" :label="p.label" @click="setNext(p)" />
        </div>
      </div>
      <div class="row q-col-gutter-sm items-center">
        <q-input v-if="!oneTime" v-model="form.batch_note" outlined dense label="Серия, срок годности" class="col-12 col-sm-5" />
        <q-input v-model="form.note" outlined dense :label="isChipping ? 'Номер чипа *' : 'Примечание'" class="col-12 col-sm-7" />
      </div>
      <div v-if="!oneTime" class="row items-center q-gutter-x-sm">
        <q-checkbox v-model="form.schedule" label="Записать на повтор в" dense />
        <q-input v-model="form.repeat_at" type="time" outlined dense style="width: 120px" :disable="!form.schedule" />
      </div>
      <div class="text-caption text-grey-7">
        <template v-if="oneTime">Однократная процедура: {{ isChipping ? 'номер чипа запишется в карточку питомца' : 'питомцу поставится отметка «стерилизован»' }}.</template>
        <template v-else>Ждущие напоминания {{ isVaccination ? 'по этой же вакцине' : 'по этому виду' }} закроются — клиенту не придёт напоминание о сделанном.</template>
      </div>
      <div v-if="error" class="text-negative">{{ error }}</div>
      <q-btn type="submit" color="primary" unelevated icon="add_task" label="Записать процедуру" :disable="!form.type" />
    </q-form>

    <div class="text-subtitle2 q-mb-xs">Профилактика питомца</div>
    <q-markup-table flat bordered dense>
      <thead><tr><th class="text-left">Дата</th><th class="text-left">Процедура</th><th class="text-left">Препарат / услуга</th><th>Следующая</th><th class="text-left">Серия, примечание</th><th /></tr></thead>
      <tbody>
        <tr v-for="p in history" :key="p.id" :class="{ 'bg-green-1': p.visit === visit.id }">
          <td>{{ fmt(p.date) }}</td>
          <td>{{ p.type_name }}{{ p.stage_label ? ` (${p.stage_label})` : '' }}</td>
          <td>{{ p.item_name }}</td>
          <td class="text-center">
            {{ p.next_date ? fmt(p.next_date) : '—' }}
            <q-badge v-if="p.next_date && p.reminder === 'closed'" color="grey-6" label="закрыто" />
          </td>
          <td>{{ [p.batch_note, p.note].filter(Boolean).join(' · ') }}</td>
          <td class="text-right">
            <q-btn v-if="canEdit && p.visit === visit.id" flat dense round size="sm" icon="delete" color="negative" @click="remove(p)" />
          </td>
        </tr>
        <tr v-if="!history.length"><td colspan="6" class="text-grey-7">Процедур не было</td></tr>
      </tbody>
    </q-markup-table>
    <div class="text-caption text-grey-7 q-mt-xs">Зелёным — процедуры этого приёма; удалить их можно только здесь.</div>
  </div>
</template>

<script setup>
// Профилактика в записи медкарты: вакцинация, дегельминтизация, обработка от паразитов,
// стерилизация, чипирование — один механизм для всех (DRY).
import { computed, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPost, fieldErrors } from '@/api'

const props = defineProps({
  visit: { type: Object, required: true },
  canEdit: { type: Boolean, default: false },
  prefill: { type: Object, default: null }, // подсказка из отмеченных в тексте позиций
})
const emit = defineEmits(['changed'])
const $q = useQuasar()
const STAGES = [{ value: 'primary', label: 'Первичная' }, { value: 'secondary', label: 'Повторная' }]
const PERIODS = [{ label: '3 недели', days: 21 }, { label: 'Месяц', months: 1 }, { label: '3 месяца', months: 3 }, { label: 'Год', months: 12 }]
const types = ref([])
const preparations = ref([])
const history = ref([])
const error = ref('')
const empty = () => ({ type: null, item: null, quantity: '1', stage: 'primary', next_date: '', batch_note: '', note: '', schedule: false, repeat_at: '10:00' })
const form = ref(empty())
const fmt = (iso) => new Date(iso).toLocaleDateString('ru-RU')

const selectedType = computed(() => types.value.find((t) => t.id === form.value.type))
const isVaccination = computed(() => selectedType.value?.kind === 'vaccination')
const isChipping = computed(() => selectedType.value?.kind === 'chipping')
const oneTime = computed(() => selectedType.value && !selectedType.value.repeat_days)

async function onType(typeId, keepItem = false) {
  if (!keepItem) form.value.item = null
  form.value.next_date = ''
  preparations.value = typeId ? ((await apiGet(`medical/preventions/preparations/?type=${typeId}`)).data ?? []) : []
}

function setNext(period) {
  const d = new Date(props.visit.date)
  if (period.days) d.setDate(d.getDate() + period.days)
  if (period.months) d.setMonth(d.getMonth() + period.months)
  form.value.next_date = d.toISOString().slice(0, 10)
}

async function loadHistory() {
  history.value = (await apiGet(`medical/preventions/?pet=${props.visit.pet}`)).data ?? []
}

async function add() {
  error.value = ''
  const body = {
    type: form.value.type, item: form.value.item, quantity: form.value.quantity || '1',
    stage: isVaccination.value ? form.value.stage : '', next_date: form.value.next_date || null,
    batch_note: form.value.batch_note, note: form.value.note,
    repeat_at: form.value.schedule && !oneTime.value ? form.value.repeat_at : null,
  }
  const { ok, data } = await apiPost(`medical/visits/${props.visit.id}/prevent/`, body)
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось записать')
  form.value = empty()
  preparations.value = []
  emit('changed', data)
  loadHistory()
  if (body.repeat_at) $q.notify({ type: 'positive', message: 'Записали на повтор в календарь' })
}

function remove(p) {
  $q.dialog({
    title: 'Удалить процедуру?', message: `${p.type_name}${p.item_name ? `: ${p.item_name}` : ''} от ${fmt(p.date)}`,
    cancel: { label: 'Отмена', flat: true }, ok: { label: 'Удалить', color: 'negative', unelevated: true },
  }).onOk(async () => {
    const { ok, data } = await apiDelete(`medical/visits/${props.visit.id}/preventions/${p.id}/`)
    if (ok) {
      emit('changed', data)
      loadHistory()
    }
  })
}

// Подсказка «записать процедуру» из медкарты: заполняем форму.
watch(() => props.prefill, async (value) => {
  if (!value) return
  form.value = { ...empty(), type: value.type, item: value.item }
  await onType(value.type, true)
}, { immediate: false })

onMounted(async () => {
  types.value = (await apiGet('medical/prevention-types/?active=true')).data ?? []
  loadHistory()
  if (props.prefill) {
    form.value = { ...empty(), type: props.prefill.type, item: props.prefill.item }
    await onType(props.prefill.type, true)
  }
})
</script>
