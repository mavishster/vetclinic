<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div class="text-subtitle1 col">Договоры</div>
      <q-btn v-if="can('clients.add_clientcontract')" flat dense color="primary" icon="add" label="Добавить"
        @click="openEditor()" />
    </q-card-section>
    <q-list separator>
      <q-item v-for="contract in contracts" :key="contract.id">
        <q-item-section avatar>
          <q-icon name="assignment" :color="contract.is_active ? 'positive' : 'grey-5'" />
        </q-item-section>
        <q-item-section>
          <q-item-label>
            № {{ contract.number }} от {{ formatDate(contract.date) }}
            <q-badge v-if="!contract.is_active" color="grey-6" label="истёк" class="q-ml-xs" />
          </q-item-label>
          <q-item-label caption>
            {{ contract.valid_until ? `действует до ${formatDate(contract.valid_until)}` : 'бессрочный' }}
            <template v-if="contract.comment"> · {{ contract.comment }}</template>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <div class="row no-wrap items-center">
            <q-btn v-if="contract.attachment" flat round dense icon="visibility"
              :href="`/api/core/attachments/${contract.attachment}/download/`" target="_blank">
              <q-tooltip>Скан: {{ contract.attachment_name }}</q-tooltip>
            </q-btn>
            <q-btn v-if="can('clients.change_clientcontract')" flat round dense icon="edit" @click="openEditor(contract)" />
            <q-btn v-if="can('clients.delete_clientcontract')" flat round dense icon="delete" color="negative"
              @click="remove(contract)" />
          </div>
        </q-item-section>
      </q-item>
      <q-item v-if="!contracts.length">
        <q-item-section class="text-grey-7">Договора нет</q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="editorOpen">
      <q-card style="width: 460px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ form.id ? 'Договор' : 'Новый договор' }}</q-card-section>
          <q-card-section class="q-pt-none q-gutter-y-sm">
            <q-input v-model="form.number" label="Номер" outlined dense
              :hint="form.id ? '' : 'Оставьте пустым — номер выдастся автоматически'" />
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.date" type="date" label="Дата" stack-label outlined dense class="col-6" />
              <q-input v-model="form.valid_until" type="date" label="Действует до" stack-label outlined dense
                class="col-6" hint="Пусто — бессрочный" />
            </div>
            <q-file v-model="scanFile" outlined dense clearable accept="image/*,application/pdf"
              :label="form.attachment ? `Заменить скан (${form.attachment_name})` : 'Скан договора (необязательно)'">
              <template #prepend><q-icon name="attach_file" /></template>
            </q-file>
            <q-input v-model="form.comment" label="Комментарий" outlined dense />
            <div v-if="error" class="text-negative">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn flat label="Отмена" v-close-popup />
            <q-btn type="submit" color="primary" unelevated label="Сохранить" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup>
// Договоры клиента. Скан загружается в файлы клиента с категорией «Договор»,
// но его можно и не загружать — достаточно отметить, что договор подписан.
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, fieldErrors } from '@/api'
import { can } from '@/session'
import { formatDate } from './pets'

const props = defineProps({ clientId: { type: String, required: true } })
const emit = defineEmits(['changed'])
const $q = useQuasar()
const contracts = ref([])
const editorOpen = ref(false)
const form = ref({})
const scanFile = ref(null)
const error = ref('')
const saving = ref(false)

async function load() {
  contracts.value = (await apiGet(`clients/contracts/?client=${props.clientId}`)).data ?? []
}

function openEditor(contract = null) {
  error.value = ''
  scanFile.value = null
  form.value = contract
    ? { ...contract }
    : { number: '', date: new Date().toISOString().slice(0, 10), valid_until: null, comment: '', attachment: null }
  editorOpen.value = true
}

async function uploadScan() {
  const categories = (await apiGet('core/file-categories/?search=Договор')).data ?? []
  const data = new FormData()
  data.append('file', scanFile.value)
  data.append('owner_type', 'clients.client')
  data.append('owner_id', props.clientId)
  const category = categories.find((c) => c.name === 'Договор')
  if (category) data.append('category', category.id)
  return apiUpload('core/attachments/', data)
}

async function save() {
  error.value = ''
  saving.value = true
  if (scanFile.value) {
    const uploaded = await uploadScan()
    if (!uploaded.ok) {
      saving.value = false
      error.value = fieldErrors(uploaded.data).file || 'Не удалось загрузить скан'
      return
    }
    form.value.attachment = uploaded.data.id
  }
  const body = {
    client: props.clientId,
    number: form.value.number,
    date: form.value.date,
    valid_until: form.value.valid_until || null,
    attachment: form.value.attachment,
    comment: form.value.comment,
  }
  const { ok, data } = form.value.id
    ? await apiPatch(`clients/contracts/${form.value.id}/`, body)
    : await apiPost('clients/contracts/', body)
  saving.value = false
  if (!ok) {
    const errors = fieldErrors(data)
    error.value = errors.non_field_errors || Object.values(errors)[0]
    return
  }
  editorOpen.value = false
  await load()
  emit('changed')
}

function remove(contract) {
  $q.dialog({
    title: 'Удалить договор?',
    message: `№ ${contract.number} от ${formatDate(contract.date)}. Скан останется в файлах клиента.`,
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
  }).onOk(async () => {
    const { ok } = await apiDelete(`clients/contracts/${contract.id}/`)
    if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось удалить договор' })
    await load()
    emit('changed')
  })
}

onMounted(load)
</script>
