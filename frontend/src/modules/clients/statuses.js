// Отметки клиента: статус и чёрный список — одинаково в списке, карточке и поиске дублей (DRY).
export const STATUS = {
  active: { label: 'активный', color: 'positive' },
  temporary: { label: 'временный', color: 'warning' },
  inactive: { label: 'неактивный', color: 'grey-6' },
}

export function clientBadges(client) {
  const badges = []
  if (client.status !== 'active') badges.push(STATUS[client.status])
  if (client.in_blacklist) badges.push({ label: 'чёрный список', color: 'negative' })
  return badges
}

export const PHONE_KINDS = [
  { value: 'mobile', label: 'Мобильный' },
  { value: 'home', label: 'Домашний' },
  { value: 'work', label: 'Рабочий' },
  { value: 'other', label: 'Другой' },
]
