// Общее для записей: статусы, действия, время (DRY — календарь, «сегодня», карточка клиента).
import { apiPost, fieldErrors } from '@/api'

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
