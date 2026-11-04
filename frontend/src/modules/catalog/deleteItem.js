// Удаление позиции прайса (товара, услуги, комбинации) — общее для окон товара и комбинации.
// Сначала спрашиваем сервер, где позиция используется: если нигде — подтверждение и удаление;
// если используется — список мест и предложение сделать её неактивной (история сохранится).
import { apiDelete, apiGet, apiPatch, fieldErrors } from '@/api'

export async function deleteItem($q, item) {
  const { ok, data } = await apiGet(`catalog/items/${item.id}/usage/`)
  if (!ok) return false
  if (data.total) {
    const places = data.places.map((p) => `• ${p.title} — ${p.count}`).join('<br>')
    return new Promise((resolve) => {
      $q.dialog({
        title: 'Удалить нельзя',
        message: `«${item.name}» уже используется:<br>${places}<br><br>Можно сделать позицию неактивной: она перестанет предлагаться для выбора, а история сохранится.`,
        html: true,
        cancel: { label: 'Отмена', flat: true },
        ok: item.is_active === false ? false : { label: 'Сделать неактивной', color: 'primary', unelevated: true },
      }).onOk(async () => {
        const result = await apiPatch(`catalog/items/${item.id}/`, { is_active: false })
        if (!result.ok) $q.notify({ type: 'negative', message: Object.values(fieldErrors(result.data))[0] || 'Не удалось' })
        resolve(result.ok ? 'deactivated' : false)
      }).onCancel(() => resolve(false))
    })
  }
  return new Promise((resolve) => {
    $q.dialog({
      title: 'Удалить позицию?',
      message: `«${item.name}» ещё нигде не использовалась — её можно удалить совсем.`,
      cancel: { label: 'Отмена', flat: true },
      ok: { label: 'Удалить', color: 'negative', unelevated: true },
    }).onOk(async () => {
      const result = await apiDelete(`catalog/items/${item.id}/`)
      if (!result.ok) $q.notify({ type: 'negative', message: Object.values(fieldErrors(result.data || {}))[0] || 'Не удалось удалить', timeout: 8000 })
      resolve(result.ok ? 'deleted' : false)
    }).onCancel(() => resolve(false))
  })
}
