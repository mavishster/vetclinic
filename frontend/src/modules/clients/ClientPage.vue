<template>
  <q-page padding>
    <div v-if="!client" class="flex flex-center q-pa-xl">
      <q-spinner v-if="loading" size="40px" color="primary" />
      <div v-else class="text-grey-7">Клиент не найден.</div>
    </div>

    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-md">
        <q-btn flat round dense icon="arrow_back" to="/clients" />
        <!-- Фото владельца: снимок с камеры (нужно согласие клиента). -->
        <q-avatar size="56px" :color="client.photo ? undefined : 'grey-3'" :text-color="client.photo ? undefined : 'grey-7'"
          class="cursor-pointer" @click="openPhoto">
          <img v-if="client.photo && !photoBroken" :src="`/api/core/attachments/${client.photo}/download/`" alt="" @error="photoBroken = true">
          <q-icon v-else name="person" />
          <q-tooltip>{{ client.photo ? 'Фото владельца — нажмите, чтобы переснять' : client.photo_consent_at ? 'Сделать фото' : 'Фото — после согласия клиента' }}</q-tooltip>
        </q-avatar>
        <h1 class="text-h5 q-my-none">{{ client.full_name }}</h1>
        <q-badge v-for="badge in clientBadges(client)" :key="badge.label" :color="badge.color" :label="badge.label" />
        <q-badge v-if="client.has_contract" color="positive" outline label="договор заключён" />
        <q-badge v-else color="warning" outline label="договора нет" />
        <q-badge v-if="client.photo_consent_at" color="positive" outline label="согласие на ПДн и фото" />
        <q-space />
        <q-btn v-if="can('clients.add_signaturerequest')" outline color="primary" icon="draw" label="На подпись" @click="signOpen = true" />
        <q-btn v-if="can('clients.change_client')" flat color="primary" icon="photo_camera" label="Фото" @click="openPhoto" />
        <q-btn v-if="can('clients.change_client')" outline color="primary" icon="edit" label="Изменить"
          @click="editorOpen = true" />
        <q-btn v-if="can('clients.change_client')" flat :icon="client.status === 'inactive' ? 'restore' : 'block'"
          :label="client.status === 'inactive' ? 'Активировать' : 'Деактивировать'" @click="toggleStatus" />
        <q-btn v-if="can('clients.delete_client')" flat color="negative" icon="delete" label="Удалить" @click="remove" />
      </div>

      <div class="row q-col-gutter-md">
        <div class="col-12 col-md-5">
          <q-card flat bordered>
            <q-list dense>
              <q-item v-for="phone in client.phones" :key="phone.number">
                <q-item-section avatar><q-icon :name="phone.is_primary ? 'phone' : 'phone_in_talk'" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label><a :href="`tel:${phone.number}`" class="text-primary">{{ phone.number }}</a></q-item-label>
                  <q-item-label caption>{{ kindLabel(phone.kind) }}{{ phone.is_primary ? ' · основной' : '' }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="!client.phones.length">
                <q-item-section class="text-grey-7">Телефон не указан</q-item-section>
              </q-item>
              <q-separator spaced />
              <q-item v-for="row in details" :key="row.label">
                <q-item-section class="text-grey-7 col-5">{{ row.label }}</q-item-section>
                <q-item-section>{{ row.value }}</q-item-section>
              </q-item>
            </q-list>
            <q-card-section v-if="client.description" class="text-body2" style="white-space: pre-line">
              {{ client.description }}
            </q-card-section>
          </q-card>
        </div>

        <div class="col-12 col-md-7">
          <div class="q-gutter-y-md">
            <ClientInvoices v-if="can('billing.view_invoice')" :client="client" />
            <ClientAppointments v-if="can('scheduling.view_appointment')" :client="client" />
            <ClientReminders v-if="can('reminders.view_reminder')" :client="client" />
            <ClientPets v-if="can('clients.view_pet')" :client="client" />
            <ClientContracts v-if="can('clients.view_clientcontract')" :client-id="client.id" @changed="reloadClient" />
            <AttachmentsBlock :key="`${client.photo}-${client.photo_consent_at}-${filesVersion}`" v-if="can('core.view_attachment')" ref="files" owner-type="clients.client"
              :owner-id="client.id" />
          </div>
        </div>
      </div>

      <ClientEditDialog v-model="editorOpen" :client="client" @saved="(data) => (client = data)" />
    </template>
    <template v-if="client">
      <SendForSignatureDialog v-model="signOpen" :client="client" @signed="load(); filesVersion++" />
      <PhotoDialog v-model="photoOpen" :client-id="client.id" @saved="(data) => (client = data)" />
    </template>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch } from '@/api'
import { can } from '@/session'
import AttachmentsBlock from '@/components/AttachmentsBlock.vue'
import PhotoDialog from '@/modules/signing/PhotoDialog.vue'
import SendForSignatureDialog from '@/modules/signing/SendForSignatureDialog.vue'
// Записи на приём — блок модуля «Календарь», встраивается в карточку клиента.
import ClientAppointments from '@/modules/scheduling/ClientAppointments.vue'
// Напоминания — блок модуля «Напоминания».
import ClientReminders from '@/modules/reminders/ClientReminders.vue'
// Счета и баланс — блок модуля «Счета».
import ClientInvoices from '@/modules/billing/ClientInvoices.vue'
import ClientContracts from './ClientContracts.vue'
import ClientEditDialog from './ClientEditDialog.vue'
import ClientPets from './ClientPets.vue'
import { clientBadges, PHONE_KINDS } from './statuses'

const props = defineProps({ id: { type: String, required: true } })
const $q = useQuasar()
const router = useRouter()
const client = ref(null)
const loading = ref(true)
const editorOpen = ref(false)
const signOpen = ref(false)
const filesVersion = ref(0) // подписанный PDF и фото появляются в «Файлах» сразу
const photoOpen = ref(false)
const photoBroken = ref(false) // файл фото не открылся — показываем значок, а не текст поверх ФИО

// Фото — только с согласием клиента на обработку ПДн и фотографирование (закон о персональных данных).
function openPhoto() {
  if (!can('clients.change_client')) return
  if (!client.value.photo_consent_at) {
    return $q.dialog({
      title: 'Нужно согласие клиента',
      message: 'Сначала клиент подписывает «Согласие на обработку ПДн и фотографирование» — кнопка «На подпись».',
      ok: { label: 'Понятно', color: 'primary', flat: true },
    })
  }
  photoOpen.value = true
}

const kindLabel = (kind) => PHONE_KINDS.find((k) => k.value === kind)?.label ?? kind
const address = computed(() =>
  [client.value.city_name, client.value.street_name, client.value.house, client.value.zip_code].filter(Boolean).join(', '),
)
const details = computed(() =>
  [
    { label: 'Адрес', value: address.value },
    { label: 'Email', value: client.value.email },
    { label: 'Скидка', value: Number(client.value.discount_percent) ? `${Number(client.value.discount_percent)} %` : '' },
    { label: '№ по журналу', value: client.value.journal_number },
    { label: 'Дисконтная карта', value: client.value.discount_card },
    { label: 'Тип', value: client.value.client_type_name },
    { label: 'Как нашли', value: client.value.source_name },
    { label: 'Паспорт', value: client.value.passport },
    { label: 'Рассылки', value: client.value.no_mailing ? 'отказался' : '' },
  ].filter((row) => row.value),
)

async function load() {
  loading.value = true
  const { ok, data } = await apiGet(`clients/clients/${props.id}/`)
  client.value = ok ? data : null
  loading.value = false
}

const files = ref(null)

// После изменения договоров обновляем отметку «договор заключён» и список файлов (скан).
async function reloadClient() {
  const { ok, data } = await apiGet(`clients/clients/${props.id}/`)
  if (ok) client.value = data
  files.value?.load()
}

async function toggleStatus() {
  const status = client.value.status === 'inactive' ? 'active' : 'inactive'
  const { ok, data } = await apiPatch(`clients/clients/${client.value.id}/`, { status })
  if (ok) client.value = data
  else $q.notify({ type: 'negative', message: 'Не удалось изменить статус' })
}

function remove() {
  $q.dialog({
    title: 'Удалить клиента?',
    message: 'Удаляйте только ошибочно созданные карточки. Если клиент просто больше не ходит — деактивируйте его.',
    cancel: { label: 'Отмена', flat: true },
    ok: { label: 'Удалить', color: 'negative', unelevated: true },
    persistent: true,
  }).onOk(async () => {
    const { ok } = await apiDelete(`clients/clients/${client.value.id}/`)
    if (ok) router.push('/clients')
    else $q.notify({ type: 'negative', message: 'Не удалось удалить клиента' })
  })
}

onMounted(load)
</script>
