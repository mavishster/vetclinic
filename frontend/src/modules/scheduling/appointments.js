// Общее для записей: статусы, действия, время (DRY — календарь, «сегодня», карточка клиента).
import { apiGet, apiPost, fieldErrors } from '@/api'

export const STATUS = {
  planned: { label: 'запланирован', color: 'primary' },
  waiting: { label: 'ожидает', color: 'warning' },
  in_progress: { label: 'у врача', color: 'info' },
  completed: { label: 'завершён', color: 'positive' },
  cancelled: { label: 'отменён', color: 'grey-6' },
  no_show: { label: 'не пришёл', color: 'grey-7' },
}

// Действия, доступные из каждого статуса (совпадают с правилами сервера).
export const ACTIONS = {
  planned: [
    { to: 'waiting', label: 'Пришёл', icon: 'how_to_reg' },
    { to: 'in_progress', label: 'К врачу', icon: 'medical_services' },
    { to: 'no_show', label: 'Не пришёл', icon: 'person_off' },
    { to: 'cancelled', label: 'Отменить', icon: 'event_busy' },
  ],
  waiting: [
    { to: 'in_progress', label: 'К врачу', icon: 'medical_services' },
    { to: 'planned', label: 'Вернуть в запланированные', icon: 'undo' },
    { to: 'cancelled', label: 'Отменить', icon: 'event_busy' },
  ],
  in_progress: [
    { to: 'completed', label: 'Приём завершён', icon: 'task_alt' },
    { to: 'waiting', label: 'Вернуть в ожидание', icon: 'undo' },
  ],
  completed: [{ to: 'in_progress', label: 'Вернуть «у врача»', icon: 'undo' }],
  cancelled: [{ to: 'planned', label: 'Восстановить запись', icon: 'restore' }],
  no_show: [
    { to: 'waiting', label: 'Всё-таки пришёл', icon: 'how_to_reg' },
    { to: 'planned', label: 'Вернуть в запланированные', icon: 'undo' },
  ],
}

const pad = (n) => String(n).padStart(2, '0')
export const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const timeOf = (iso) => {
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Сменить статус; для отмены спросить причину. Возвращает обновлённую запись или null.
export async function changeStatus($q, appointment, to) {
  let reason = ''
  if (to === 'cancelled') {
    reason = await new Promise((resolve) =>
      $q
        .dialog({
          title: 'Отменить запись?', message: 'Причина отмены', prompt: { model: '', type: 'text' },
          cancel: { label: 'Назад', flat: true }, ok: { label: 'Отменить запись', color: 'negative', unelevated: true },
        })
        .onOk((text) => resolve(text))
        .onCancel(() => resolve(null)),
    )
    if (reason === null) return null
  }
  const { ok, data } = await apiPost(`scheduling/appointments/${appointment.id}/status/`, { status: to, reason })
  if (!ok) {
    $q.notify({ type: 'negative', message: fieldErrors(data).non_field_errors || 'Не удалось сменить статус' })
    return null
  }
  return data
}

// --- Электронная очередь ---

// Порядок ожидания — как на экране в холле: по времени записи, а пришедшие позже
// своего времени и без записи — по времени прихода.
const queueKey = (a) => Math.max(+new Date(a.start), a.arrived_at ? +new Date(a.arrived_at) : 0)
export const byQueue = (a, b) => queueKey(a) - queueKey(b) || (a.queue_number ?? 0) - (b.queue_number ?? 0)

async function pickRoom($q, appointment) {
  const { ok, data } = await apiGet(`scheduling/appointments/${appointment.id}/invite/`)
  if (!ok) {
    $q.notify({ type: 'negative', message: 'Не удалось загрузить кабинеты' })
    return null
  }
  if (!data.rooms.length) {
    $q.notify({ type: 'warning', message: 'Нет ни одного кабинета — добавьте их в «Справочники → Кабинеты».' })
    return null
  }
  return new Promise((resolve) =>
    $q
      .dialog({
        title: 'В какой кабинет?',
        options: { type: 'radio', model: data.suggested ?? data.rooms[0].id, items: data.rooms.map((r) => ({ label: r.name, value: r.id })) },
        cancel: { label: 'Назад', flat: true },
        ok: { label: 'Пригласить', color: 'primary', unelevated: true },
      })
      .onOk((room) => resolve(room))
      .onCancel(() => resolve(null)),
  )
}

// Пригласить ожидающего в кабинет — он появится на экране очереди в холле.
// Кабинет спрашивается, только если сервер его не знает (первое приглашение врача за день)
// или если выбрать его просят явно (chooseRoom). Возвращает обновлённую запись или null.
export async function inviteToRoom($q, appointment, chooseRoom = false) {
  let room = chooseRoom ? await pickRoom($q, appointment) : null
  if (chooseRoom && !room) return null
  const url = `scheduling/appointments/${appointment.id}/invite/`
  let result = await apiPost(url, room ? { room } : {})
  if (!result.ok && result.data?.room && !room) {
    room = await pickRoom($q, appointment)
    if (!room) return null
    result = await apiPost(url, { room })
  }
  if (!result.ok) {
    const errors = fieldErrors(result.data)
    $q.notify({ type: 'negative', message: errors.non_field_errors || errors.room || 'Не удалось пригласить' })
    return null
  }
  $q.notify({ type: 'positive', message: `№ ${result.data.queue_number} — приглашён: ${result.data.room_name}` })
  return result.data
}
