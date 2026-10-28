// Единая точка обращения к API (DRY): адрес, cookies и разбор ответа — здесь.
// Запись (POST/PUT) добавим вместе с первым экраном, которому она нужна (YAGNI).

export async function apiGet(path) {
  const response = await fetch(`/api/${path}`, { credentials: 'same-origin' })
  const data = await response.json().catch(() => null)
  return { ok: response.ok, status: response.status, data }
}
