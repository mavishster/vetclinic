<template>
  <div class="queue-screen">
    <header class="top">
      <img v-if="logo" :src="logo" alt="" class="logo" @error="logo = null" />
      <div class="clinic">{{ clinic }}</div>
      <div class="clock">{{ clock }}</div>
    </header>

    <main class="board">
      <section class="called">
        <h2>Проходите</h2>
        <div v-if="!called.length" class="empty">Здесь появится номер, когда врач пригласит в кабинет</div>
        <div v-for="item in called.slice(0, 4)" :key="item.id + item.called_at" class="call" :class="{ fresh: isFresh(item) }">
          <div class="call-number">{{ item.number }}</div>
          <div class="call-pet">{{ item.pet || '—' }}</div>
          <div class="call-room">{{ item.room }}</div>
        </div>
      </section>

      <section class="waiting">
        <h2>Ожидают</h2>
        <div v-if="!waiting.length" class="empty">Очереди нет</div>
        <div v-for="item in waiting.slice(0, WAITING_SHOWN)" :key="item.id" class="wait">
          <span class="wait-number">{{ item.number }}</span>
          <span class="wait-pet">{{ item.pet || '—' }}</span>
          <span class="wait-doctor">{{ item.doctor || 'любой врач' }}</span>
        </div>
        <div v-if="waiting.length > WAITING_SHOWN" class="more">и ещё {{ waiting.length - WAITING_SHOWN }}</div>
      </section>
    </main>

    <footer class="bottom">
      <span v-if="offline" class="offline">Нет связи с сервером — показаны последние данные</span>
      <span v-else>Номер в очереди вам назовут на стойке регистрации</span>
      <span class="controls">
        <button v-if="voiceWanted && !soundOn" type="button" class="sound" @click="enableSound">Включить звук</button>
        <button type="button" class="exit" @click="exit">{{ isDevice ? 'Выйти' : 'Закрыть' }}</button>
      </span>
    </footer>
  </div>
</template>

<script setup>
// Экран очереди для телевизора в холле. Раз в 3 секунды спрашивает сервер, кто ожидает
// и кого пригласили; новое приглашение отмечается звуком и, если можно, голосом.
// Показывает только номер, кличку, врача и кабинет — без ФИО и телефонов.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '@/api'
import { logout, session } from '@/session'
import { logoUrl } from '@/modules/core/logo'

const POLL_MS = 3000
const FRESH_MS = 30000 // столько секунд новое приглашение подсвечено
const WAITING_SHOWN = 10

const route = useRoute()
const router = useRouter()
const clinic = session.user?.clinic || 'Ветеринарная клиника'
const logo = ref(logoUrl(session.user?.clinic_logo))
const called = ref([])
const waiting = ref([])
const offline = ref(false)
const clock = ref('')
const now = ref(Date.now())
// Голос: ?voice=0 в адресе — только звуковой сигнал.
const voiceWanted = route.query.voice !== '0'
const soundOn = ref(false)
const isDevice = computed(() => (session.user?.permissions || []).length === 1 && !session.user?.is_superuser)

let audio = null
let seen = null // id+called_at уже объявленных приглашений; null — первая загрузка
let pending = []
let speaking = false
let failures = 0
let pollTimer = null
let clockTimer = null
let wakeLock = null

const isFresh = (item) => now.value - new Date(item.called_at).getTime() < FRESH_MS

async function poll() {
  const { ok, data } = await apiGet('scheduling/queue/')
  if (!ok) {
    failures += 1
    offline.value = failures >= 3
    return
  }
  failures = 0
  offline.value = false
  called.value = data.called
  waiting.value = data.waiting
  const keys = data.called.map((c) => `${c.id}|${c.called_at}`)
  if (seen) {
    // Старые приглашения первыми — объявляем в том порядке, в каком приглашали.
    const fresh = data.called.filter((c) => !seen.has(`${c.id}|${c.called_at}`)).reverse()
    pending.push(...fresh)
    announceNext()
  }
  seen = new Set([...(seen ?? []), ...keys])
}

// --- Звук ---
// Браузер разрешает звук только после нажатия на странице — отсюда кнопка «Включить звук».
function enableSound() {
  const Context = window.AudioContext || window.webkitAudioContext
  if (Context) {
    audio = audio || new Context()
    audio.resume()
  }
  soundOn.value = true
  chime()
}

function chime() {
  if (!audio) return
  // «Динь-дон»: две мягкие ноты.
  ;[
    [659, 0],
    [523, 0.35],
  ].forEach(([freq, delay]) => {
    const osc = audio.createOscillator()
    const gain = audio.createGain()
    const start = audio.currentTime + delay
    osc.frequency.value = freq
    gain.gain.setValueAtTime(0.0001, start)
    gain.gain.exponentialRampToValueAtTime(0.4, start + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.9)
    osc.connect(gain).connect(audio.destination)
    osc.start(start)
    osc.stop(start + 1)
  })
}

function russianVoice() {
  return window.speechSynthesis?.getVoices().find((v) => v.lang?.toLowerCase().startsWith('ru')) ?? null
}

function announceNext() {
  if (speaking || !pending.length) return
  const item = pending.shift()
  speaking = true
  chime()
  const voice = voiceWanted && soundOn.value ? russianVoice() : null
  const done = () => {
    speaking = false
    setTimeout(announceNext, 500)
  }
  if (!voice) return setTimeout(done, 1500)
  const phrase = new SpeechSynthesisUtterance(`Номер ${item.number}. ${item.pet || ''}. ${item.room}.`)
  phrase.voice = voice
  phrase.lang = voice.lang
  phrase.rate = 0.9
  phrase.onend = done
  phrase.onerror = done
  setTimeout(() => window.speechSynthesis.speak(phrase), 1200) // после сигнала
}

// --- Экран не гаснет ---
async function keepAwake() {
  try {
    wakeLock = await navigator.wakeLock?.request('screen')
  } catch {
    wakeLock = null
  }
}
function onVisible() {
  if (document.visibilityState === 'visible') keepAwake()
}

function tick() {
  now.value = Date.now()
  clock.value = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function exit() {
  if (!isDevice.value) return router.push('/appointments/today')
  await logout()
  router.push('/login')
}

onMounted(() => {
  tick()
  poll()
  pollTimer = setInterval(poll, POLL_MS)
  clockTimer = setInterval(tick, 1000)
  keepAwake()
  document.addEventListener('visibilitychange', onVisible)
  window.speechSynthesis?.getVoices() // голоса в браузере загружаются не сразу
})
onUnmounted(() => {
  clearInterval(pollTimer)
  clearInterval(clockTimer)
  document.removeEventListener('visibilitychange', onVisible)
  wakeLock?.release?.()
  window.speechSynthesis?.cancel()
  audio?.close?.()
})
</script>

<style scoped>
/* Телевизор в холле: читается с 3–5 метров, тёмный фон не бликует и не слепит.
   Размеры — от ширины экрана, чтобы одинаково смотрелось на 32" и 55". */
.queue-screen {
  --bg: #0e2229;
  --panel: #15313a;
  --line: #24464f;
  --text: #f1f4f2;
  --muted: #9fb6b8;
  --call: #f7f4ea;
  --call-text: #0e2229;
  --accent: #f2b33d;
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  overflow: hidden;
}
.top {
  display: flex;
  align-items: center;
  gap: 1.2vw;
  padding: 1.4vw 2.5vw;
  border-bottom: 1px solid var(--line);
}
.logo {
  height: 3.4vw;
  max-width: 10vw;
  object-fit: contain;
}
.clinic {
  flex: 1;
  font-size: 1.9vw;
  font-weight: 500;
}
.clock {
  font-size: 2.6vw;
  font-variant-numeric: tabular-nums;
}
.board {
  flex: 1;
  display: grid;
  grid-template-columns: 1.35fr 1fr;
  gap: 2.5vw;
  padding: 2vw 2.5vw;
  min-height: 0;
}
h2 {
  margin: 0 0 1.2vw;
  font-size: 1.6vw;
  font-weight: 500;
  color: var(--muted);
  letter-spacing: 0.02em;
}
.empty {
  font-size: 1.5vw;
  color: var(--muted);
}
.call {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 2vw;
  padding: 1.3vw 2vw;
  margin-bottom: 1vw;
  border-radius: 1vw;
  background: var(--panel);
  border: 2px solid var(--line);
}
.call.fresh {
  background: var(--call);
  color: var(--call-text);
  border-color: var(--accent);
  animation: arrive 0.6s ease-out, blink 1.2s ease-in-out 0.6s 3;
}
.call-number {
  font-size: 5.6vw;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  min-width: 7vw;
}
.call-pet {
  font-size: 2.6vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.call-room {
  font-size: 2.8vw;
  font-weight: 700;
  text-align: right;
  white-space: nowrap;
}
.wait {
  display: grid;
  grid-template-columns: 5vw 1fr auto;
  align-items: baseline;
  gap: 1vw;
  padding: 0.75vw 0;
  border-bottom: 1px solid var(--line);
  font-size: 1.8vw;
}
.wait-number {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.wait-pet {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wait-doctor {
  color: var(--muted);
  font-size: 1.5vw;
}
.more {
  margin-top: 1vw;
  font-size: 1.5vw;
  color: var(--muted);
}
.bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.9vw 2.5vw;
  border-top: 1px solid var(--line);
  font-size: 1.2vw;
  color: var(--muted);
}
.offline {
  color: var(--accent);
}
.controls {
  display: flex;
  gap: 0.8vw;
}
.controls button {
  font: inherit;
  font-size: 1vw;
  color: var(--muted);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 0.4vw;
  padding: 0.3vw 0.9vw;
  cursor: pointer;
}
.controls .sound {
  color: var(--call-text);
  background: var(--accent);
  border-color: var(--accent);
  font-size: 1.3vw;
}
@keyframes arrive {
  from {
    transform: translateY(-1.5vw);
    opacity: 0;
  }
}
@keyframes blink {
  50% {
    border-color: transparent;
  }
}
@media (prefers-reduced-motion: reduce) {
  .call.fresh {
    animation: none;
  }
}
/* Вертикальный экран или узкое окно: блоки друг под другом. */
@media (max-aspect-ratio: 1/1) {
  .board {
    grid-template-columns: 1fr;
  }
}
</style>
