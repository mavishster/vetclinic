// Личное оформление: тема и основной цвет. Хранятся в учётной записи на сервере —
// у каждого сотрудника свои, на любом компьютере. Применяются сразу после входа.
import { Dark, setCssVar } from 'quasar'

export const DEFAULT_PRIMARY = '#24566a' // петроль — цвет системы по умолчанию

// Готовые цвета: спокойные, с хорошей читаемостью белого текста на шапке.
export const PALETTE = [
  { name: 'Петроль', color: '#24566a' },
  { name: 'Синий', color: '#1f5fa8' },
  { name: 'Изумруд', color: '#2e7d5b' },
  { name: 'Оливковый', color: '#5b6b2f' },
  { name: 'Бордо', color: '#8c2f39' },
  { name: 'Сливовый', color: '#6b4c9a' },
  { name: 'Графит', color: '#3f4a52' },
  { name: 'Терракота', color: '#a24b2a' },
]

export function applyUiSettings(settings = {}) {
  const theme = settings.theme || 'auto'
  Dark.set(theme === 'auto' ? 'auto' : theme === 'dark')
  setCssVar('primary', settings.primary || DEFAULT_PRIMARY)
}
