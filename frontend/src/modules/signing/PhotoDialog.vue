<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)" @hide="stop">
    <q-card style="width: 560px; max-width: 96vw">
      <q-card-section class="text-h6">Фото владельца</q-card-section>
      <q-card-section v-if="stations.length" class="q-pt-none">
        <q-btn-toggle v-model="source" no-caps unelevated spread toggle-color="primary" :disable="!!request"
          :options="[{ label: 'Камера этого компьютера', value: 'here', icon: 'videocam' },
                     ...stations.map((s) => ({ label: `Планшет «${s.name}»`, value: s.id, icon: 'tablet_mac' }))]"
          @update:model-value="switchSource" />
      </q-card-section>
      <q-card-section class="q-pt-none">
        <div v-if="error" class="text-negative q-mb-sm">{{ error }}</div>
        <template v-if="source === 'here'">
          <video v-show="!shot" ref="video" autoplay playsinline muted class="frame" />
          <img v-if="shot" :src="shot" class="frame" alt="Снимок" />
          <canvas ref="canvas" style="display: none" />
        </template>
        <div v-else class="text-center q-pa-lg">
          <template v-if="!request">На планшете включится камера, клиент посмотрит в неё и нажмёт «Снять».</template>
          <template v-else-if="request.status === 'pending'">
            <q-spinner-dots size="40px" color="primary" />
            <div class="q-mt-sm">Камера на планшете «{{ request.station_name }}» включена. Ждём снимок…</div>
          </template>
          <template v-else-if="request.status === 'done'">
            <img :src="`/api/core/attachments/${request.result}/download/`" class="frame" alt="Снимок с планшета" />
          </template>
          <div v-else class="text-grey-7">Отменено</div>
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn v-if="request?.status === 'pending'" flat color="negative" label="Отменить" @click="cancelRequest" />
        <q-btn flat :label="request?.status === 'done' ? 'Готово' : 'Отмена'" v-close-popup />
        <q-btn v-if="source !== 'here' && !request" color="primary" unelevated icon="tablet_mac" label="Снять на планшете" @click="askTablet" />
        <template v-else-if="source !== 'here'" />
        <template v-else-if="!shot">
          <q-btn color="primary" unelevated icon="photo_camera" label="Снять" :disable="!ready" @click="take" />
        </template>
        <template v-else>
          <q-btn flat icon="replay" label="Переснять" @click="shot = null" />
          <q-btn color="primary" unelevated icon="save" label="Сохранить" :loading="saving" @click="save" />
        </template>
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
// Снимок с веб-камеры или камеры планшета. Браузер даёт камеру только по https (или localhost).
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { apiGet, apiPost, apiUpload, fieldErrors } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false }, clientId: { type: String, required: true } })
const emit = defineEmits(['update:modelValue', 'saved'])
const video = ref(null)
const canvas = ref(null)
const shot = ref(null)
const ready = ref(false)
const saving = ref(false)
const error = ref('')
let stream = null
const stations = ref([])
const source = ref('here')
const request = ref(null)
let timer = null

watch(() => props.modelValue, async (open) => {
  if (!open) return
  request.value = null
  stations.value = (await apiGet('clients/signing-stations/?active=true')).data ?? []
  source.value = 'here'
  startCamera()
})

function switchSource(value) {
  if (value === 'here') return startCamera()
  stop()
}

// --- Снимок камерой планшета: запрос → планшет снимает → фото в карточке ---
async function askTablet() {
  error.value = ''
  const { ok, data } = await apiPost('clients/photo-requests/', { client: props.clientId, station: source.value })
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось отправить на планшет')
  request.value = data
  timer = setInterval(checkTablet, 2000)
}
async function checkTablet() {
  const { ok, data } = await apiGet(`clients/photo-requests/${request.value.id}/`)
  if (!ok) return
  request.value = data
  if (data.status === 'pending') return
  clearInterval(timer)
  if (data.status === 'done') {
    const client = await apiGet(`clients/clients/${props.clientId}/`)
    if (client.ok) emit('saved', client.data)
  }
}
async function cancelRequest() {
  await apiPost(`clients/photo-requests/${request.value.id}/cancel/`)
  checkTablet()
}
onUnmounted(() => clearInterval(timer))

async function startCamera() {
  shot.value = null
  error.value = ''
  ready.value = false
  if (!navigator.mediaDevices?.getUserMedia) {
    return (error.value = 'Камера недоступна: браузер разрешает её только по защищённому адресу (https). Настроим при установке в клинике.')
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
    await nextTick()
    video.value.srcObject = stream
    ready.value = true
  } catch (e) {
    error.value = e?.name === 'NotAllowedError' ? 'Доступ к камере запрещён — разрешите его в настройках браузера.' : 'Камера не найдена или занята другой программой.'
  }
}

function take() {
  const v = video.value
  canvas.value.width = v.videoWidth
  canvas.value.height = v.videoHeight
  canvas.value.getContext('2d').drawImage(v, 0, 0)
  shot.value = canvas.value.toDataURL('image/jpeg', 0.9)
}

async function save() {
  saving.value = true
  const blob = await new Promise((resolve) => canvas.value.toBlob(resolve, 'image/jpeg', 0.9))
  const form = new FormData()
  form.append('file', blob, 'photo.jpg')
  const { ok, data } = await apiUpload(`clients/clients/${props.clientId}/photo/`, form)
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  emit('saved', data)
  emit('update:modelValue', false)
}

function stop() {
  stream?.getTracks().forEach((t) => t.stop()) // камера выключается, как только окно закрыто
  stream = null
  clearInterval(timer)
}
</script>

<style scoped>
.frame {
  width: 100%;
  border-radius: 8px;
  background: #000;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}
</style>
