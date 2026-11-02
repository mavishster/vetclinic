<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)" @hide="stop">
    <q-card style="width: 560px; max-width: 96vw">
      <q-card-section class="text-h6">Фото владельца</q-card-section>
      <q-card-section class="q-pt-none">
        <div v-if="error" class="text-negative q-mb-sm">{{ error }}</div>
        <video v-show="!shot" ref="video" autoplay playsinline muted class="frame" />
        <img v-if="shot" :src="shot" class="frame" alt="Снимок" />
        <canvas ref="canvas" style="display: none" />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Отмена" v-close-popup />
        <template v-if="!shot">
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
import { nextTick, ref, watch } from 'vue'
import { fieldErrors, apiUpload } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false }, clientId: { type: String, required: true } })
const emit = defineEmits(['update:modelValue', 'saved'])
const video = ref(null)
const canvas = ref(null)
const shot = ref(null)
const ready = ref(false)
const saving = ref(false)
const error = ref('')
let stream = null

watch(() => props.modelValue, async (open) => {
  if (!open) return
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
})

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
