// Общие функции для питомцев: возраст, пол (DRY — список, карточка, клиент).

export const SEX = [
  { value: 'male', label: 'Самец', short: '♂' },
  { value: 'female', label: 'Самка', short: '♀' },
  { value: 'unknown', label: 'Не указан', short: '' },
]

export const sexLabel = (pet) => SEX.find((s) => s.value === pet.sex)?.label ?? ''

function plural(n, one, few, many) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}

// «3 года 4 мес.», «≈ 2 года», «5 мес.», «12 дн.» — от даты рождения до сегодня или до даты смерти.
export function ageText(pet) {
  if (!pet.birth_date) return ''
  const from = new Date(pet.birth_date)
  const to = pet.death_date ? new Date(pet.death_date) : new Date()
  let months = (to.getFullYear() - from.getFullYear()) * 12 + (to.getMonth() - from.getMonth())
  if (to.getDate() < from.getDate()) months -= 1
  const years = Math.floor(months / 12)
  const restMonths = months % 12
  const parts = []
  if (years) parts.push(`${years} ${plural(years, 'год', 'года', 'лет')}`)
  if (restMonths) parts.push(`${restMonths} мес.`)
  if (!parts.length) parts.push(`${Math.max(0, Math.round((to - from) / 86400000))} дн.`)
  return `${pet.birth_date_approximate ? '≈ ' : ''}${parts.join(' ')}`
}

// Приблизительная дата рождения по возрасту: «3 года 2 месяца» → дата 3 года 2 месяца назад.
export function birthDateFromAge(years, months) {
  const date = new Date()
  date.setMonth(date.getMonth() - (Number(years) || 0) * 12 - (Number(months) || 0))
  return date.toISOString().slice(0, 10)
}

export const formatDate = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '')
