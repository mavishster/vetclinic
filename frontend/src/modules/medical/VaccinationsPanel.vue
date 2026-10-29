<template>
  <div>
    <q-form v-if="canEdit" class="q-gutter-y-sm q-mb-md" @submit="add">
      <div class="row q-col-gutter-sm">
        <q-select v-model="form.vaccine" :options="vaccines" option-value="id" option-label="name" emit-value map-options
          outlined dense label="Вакцина" class="col-12 col-sm-7"
          :hint="vaccines.length ? '' : 'Вакцины — товары из групп с отметкой «показывать в вакцинациях»'" />
        <q-input v-model="form.quantity" type="number" step="0.001" min="0" outlined dense label="Кол-во" class="col-4 col-sm-2" />
        <q-select v-model="form.kind" :options="KINDS" emit-value map-options outlined dense label="Тип" class="col-8 col-sm-3" />
      </div>
      <div class="row q-col-gutter-sm items-center">
        <q-input v-model="form.next_date" type="date" outlined dense stack-label label="Следующая" class="col-12 col-sm-5" />
        <div class="col-12 col-sm-7 q-gutter-x-xs">
          <q-btn v-for="p in PERIODS" :key="p.label" outline dense no-caps size="sm" :label="p.label" @click="setNext(p)" />
        </div>
      </div>
      <div class="row q-col-gutter-sm items-center">
        <q-input v-model="form.batch_note" outlined dense label="Серия, срок годности" class="col-12 col-sm-6" />
        <div class="col-auto"><q-checkbox v-model="form.schedule" label="Записать на повтор в" dense :disable="!form.next_date" /></div>
        <q-input v-model="form.repeat_at" type="time" outlined dense class="col-auto" style="width: 120px" :disable="!form.schedule" />
      </div>
      <div class="text-caption text-grey-7">Действующие напоминания по этой же вакцине закроются — клиенту не придёт напоминание о сделанном.</div>
      <div v-if="error" class="text-negative">{{ error }}</div>
      <q-btn type="submit" color="primary" unelevated icon="vaccines" label="Добавить вакцинацию" :disable="!form.vaccine" />
    </q-form>

    <div class="text-subtitle2 q-mb-xs">История вакцинаций питомца</div>
    <q-markup-table flat bordered dense>
      <thead><tr><th class="text-left">Дата</th><th class="text-left">Вакцина</th><th>Тип</th><th>Следующая</th><th class="text-left">Серия</th><th /></tr></thead>
      <tbody>
        <tr v-for="v in history" :key="v.id" :class="{ 'bg-green-1': v.visit === visit.id }">
          <td>{{ fmt(v.date) }}</td>
          <td>{{ v.vaccine_name }}</td>
          <td class="text-center">{{ v.kind_label }}</td>
          <td class="text-center">
            {{ v.next_date ? fmt(v.next_date) : '—' }}
            <q-badge v-if="v.next_date && v.reminder === 'closed'" color="grey-6" label="закрыто" />
          </td>
          <td>{{ v.batch_note }}</td>
          <td class="text-right">
            <q-btn v-if="canEdit && v.visit === visit.id" flat dense round size="sm" icon="delete" color="negative" @click="remove(v)" />
          </td>
        </tr>
        <tr v-if="!history.length"><td colspan="6" class="text-grey-7">Вакцинаций не было</td></tr>
      </tbody>
    </q-markup-table>
    <div class="text-caption text-grey-7 q-mt-xs">Зелёным — вакцинации этого приёма; изменить их можно только здесь.</div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPost, fieldErrors } from '@/api'

const props = defineProps({ visit: { type: Object, required: true }, canEdit: { type: Boolean, default: false } })
const emit = defineEmits(['changed'])
const $q = useQuasar()
const KINDS = [{ value: 'primary', label: 'Первичная' }, { value: 'secondary', label: 'Повторная' }]
const PERIODS = [{ label: '3 недели', days: 21 }, { label: 'Месяц', months: 1 }, { label: 'Год', months: 12 }]
const vaccines = ref([])
const history = ref([])
const error = ref('')
const empty = () => ({ vaccine: null, quantity: '1', kind: 'primary', next_date: '', batch_note: '', schedule: false, repeat_at: '10:00' })
const form = ref(empty())
const fmt = (iso) => new Date(iso).toLocaleDateString('ru-RU')

function setNext(period) {
  const d = new Date(props.visit.date)
  if (period.days) d.setDate(d.getDate() + period.days)
  if (period.months) d.setMonth(d.getMonth() + period.months)
  form.value.next_date = d.toISOString().slice(0, 10)
}

async function loadHistory() {
  history.value = (await apiGet(`medical/vaccinations/?pet=${props.visit.pet}`)).data ?? []
}

async function add() {
  error.value = ''
  const body = {
    vaccine: form.value.vaccine, quantity: form.value.quantity || '1', kind: form.value.kind,
    next_date: form.value.next_date || null, batch_note: form.value.batch_note,
    repeat_at: form.value.schedule && form.value.next_date ? form.value.repeat_at : null,
  }
  const { ok, data } = await apiPost(`medical/visits/${props.visit.id}/vaccinate/`, body)
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось добавить')
  form.value = empty()
  emit('changed', data)
  loadHistory()
  if (body.repeat_at) $q.notify({ type: 'positive', message: 'Записали на ревакцинацию' })
}

function remove(v) {
  $q.dialog({
    title: 'Удалить вакцинацию?', message: `${v.vaccine_name} от ${fmt(v.date)}`,
    cancel: { label: 'Отмена', flat: true }, ok: { label: 'Удалить', color: 'negative', unelevated: true },
  }).onOk(async () => {
    const { ok, data } = await apiDelete(`medical/visits/${props.visit.id}/vaccinations/${v.id}/`)
    if (ok) {
      emit('changed', data)
      loadHistory()
    }
  })
}

onMounted(async () => {
  vaccines.value = (await apiGet('medical/vaccines/')).data ?? []
  loadHistory()
})
</script>
