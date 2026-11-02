<template>
  <div class="signing-screen">
    <!-- Ожидание -->
    <div v-if="!doc && !thanks" class="idle column flex-center">
      <q-icon name="draw" size="72px" color="primary" />
      <div class="text-h5 q-mt-md">{{ clinic }}</div>
      <div class="text-subtitle1 text-grey-7 q-mt-sm">Ожидание документа на подпись…</div>
      <div class="text-caption text-grey-6 q-mt-xl">{{ station }}</div>
      <!-- Только в ожидании: сменить учётную запись (например, если в этом браузере нужно войти сотруднику). -->
      <q-btn flat dense no-caps size="sm" color="grey-6" icon="logout" label="Выйти" class="exit" @click="exit" />
    </div>

    <!-- Спасибо -->
    <div v-else-if="thanks" class="idle column flex-center">
      <q-icon name="task_alt" size="96px" color="positive" />
      <div class="text-h4 q-mt-md">Спасибо!</div>
      <div class="text-subtitle1 text-grey-7 q-mt-sm">Документ подписан</div>
    </div>

    <!-- Документ и подпись -->
    <div v-else class="column no-wrap full-height">
      <div class="q-pa-sm text-subtitle1 text-weight-medium">{{ doc.title }} · {{ doc.client_name }}</div>
      <!-- Документ — в изолированной рамке: его оформление не влияет на экран. -->
      <iframe class="doc col" :srcdoc="doc.html" sandbox="" title="Документ" />
      <div class="pad-area q-pa-sm">
        <div class="text-caption text-grey-8 q-mb-xs">Прочитайте документ и распишитесь в поле ниже</div>
        <canvas ref="pad" class="pad" @pointerdown="start" @pointermove="move" @pointerup="end" @pointerleave="end" />
        <div class="row q-gutter-sm q-mt-sm">
          <q-btn outline size="lg" icon="backspace" label="Стереть" @click="clear" />
          <q-space />
          <q-btn color="primary" unelevated size="lg" icon="draw" label="Подписать" :loading="sending" :disable="!enough" @click="sign" />
        </div>
        <div v-if="error" class="text-negative q-mt-xs">{{ error }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Экран подписи на планшете у стойки. Раз в 2 секунды спрашивает сервер, нет ли документа;
// клиент читает его, расписывается пальцем или стилусом и нажимает «Подписать».
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { apiGet, apiPost, fieldErrors } from '@/api'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { logout, session } from '@/session'

const router = useRouter()
const $q = useQuasar()
const doc = ref(null)
const thanks = ref(false)
const station = ref('')
const clinic = ref(session.user?.clinic_name || 'Ветеринарная клиника')
const pad = ref(null)
const sending = ref(false)
const error = ref('')
const length = ref(0)
const enough = ref(false)
let drawing = false
let last = null
let timer = null
let wakeLock = null

async function poll() {
  if (sending.value || thanks.value) return
  const { ok, data } = await apiGet('clients/signing/current/')
  if (!ok) return
  station.value = data.station
  if (!data.id) return (doc.value = null)
  if (doc.value?.id === data.id) return
  doc.value = data
  error.value = ''
  await nextTick()
  setupPad()
}

// --- Поле подписи (canvas): линия по точкам касания ---
function setupPad() {
  const canvas = pad.value
  if (!canvas) return
  const ratio = window.devicePixelRatio || 1
  canvas.width = canvas.clientWidth * ratio
  canvas.height = canvas.clientHeight * ratio
  const ctx = canvas.getContext('2d')
  ctx.scale(ratio, ratio)
  ctx.lineWidth = 2.5
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#111'
  length.value = 0
  enough.value = false
}
const point = (e) => {
  const rect = pad.value.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}
function start(e) {
  e.preventDefault()
  pad.value.setPointerCapture(e.pointerId)
  drawing = true
  last = point(e)
}
function move(e) {
  if (!drawing) return
  const p = point(e)
  const ctx = pad.value.getContext('2d')
  ctx.beginPath()
  ctx.moveTo(last.x, last.y)
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
  length.value += Math.hypot(p.x - last.x, p.y - last.y)
  enough.value = length.value > 60 // случайное касание — не подпись
  last = p
}
function end() {
  drawing = false
}
function clear() {
  const canvas = pad.value
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
  length.value = 0
  enough.value = false
}

async function sign() {
  error.value = ''
  sending.value = true
  const { ok, data } = await apiPost('clients/signing/sign/', { id: doc.value.id, signature: pad.value.toDataURL('image/png') })
  sending.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось подписать')
  doc.value = null
  thanks.value = true
  setTimeout(() => (thanks.value = false), 4000)
}

function exit() {
  $q.dialog({ title: 'Выйти с экрана подписи?', message: 'Планшет перестанет получать документы, пока под ним снова не войдут.',
    cancel: { label: 'Остаться', flat: true }, ok: { label: 'Выйти', color: 'primary', unelevated: true } })
    .onOk(async () => { await logout(); router.replace('/login') })
}

onMounted(async () => {
  poll()
  timer = setInterval(poll, 2000)
  try {
    wakeLock = await navigator.wakeLock?.request('screen') // экран не гаснет
  } catch {
    wakeLock = null
  }
})
onUnmounted(() => {
  clearInterval(timer)
  wakeLock?.release?.()
})
</script>

<style scoped>
.signing-screen {
  position: fixed;
  inset: 0;
  background: #fff;
  color: #111;
}
.idle {
  height: 100%;
  position: relative;
}
.exit {
  position: absolute;
  right: 12px;
  bottom: 12px;
}
.full-height {
  height: 100%;
}
.doc {
  border: 0;
  border-top: 1px solid #ddd;
  border-bottom: 1px solid #ddd;
  width: 100%;
  background: #fff;
}
.pad {
  width: 100%;
  height: 180px;
  border: 2px dashed #9aa;
  border-radius: 8px;
  background: #fafafa;
  touch-action: none; /* касания рисуют подпись, а не листают страницу */
}
</style>
