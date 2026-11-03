// Деньги на экране: 1 234,50 сом (одинаково во всех модулях — DRY).
// Валюта приходит с сервера (настройка CURRENCY), по умолчанию — сом.
import { session } from '@/session'

const formatter = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
export const currency = () => session.user?.currency || 'сом'
export const money = (value) => (value === null || value === undefined || value === '' ? '' : `${formatter.format(Number(value))} ${currency()}`)
