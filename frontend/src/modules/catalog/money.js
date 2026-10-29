// Деньги на экране: 1 234,50 ₽ (одинаково во всех модулях — DRY).
const formatter = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
export const money = (value) => (value === null || value === undefined || value === '' ? '' : `${formatter.format(Number(value))} ₽`)
