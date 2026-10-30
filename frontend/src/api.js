// Единая точка обращения к API (DRY): адрес, cookies, CSRF и разбор ответа — здесь.

function csrfToken() {
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? ''
}

async function request(method, path, body) {
  const options = { method, credentials: 'same-origin', headers: {} }
  if (method !== 'GET') options.headers['X-CSRFToken'] = csrfToken()
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }
  const response = await fetch(`/api/${path}`, options)
  const data = response.status === 204 ? null : await response.json().catch(() => null)
  return { ok: response.ok, status: response.status, data }
}

// Загрузка файла (multipart). FormData собирает вызывающий код.
export async function apiUpload(path, formData) {
  const response = await fetch(`/api/${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRFToken': csrfToken() },
    body: formData,
  })
  const data = await response.json().catch(() => null)
  return { ok: response.ok, status: response.status, data }
}

export const apiGet = (path) => request('GET', path)
export const apiPost = (path, body) => request('POST', path, body)
export const apiPatch = (path, body) => request('PATCH', path, body)
export const apiDelete = (path) => request('DELETE', path)

// Ошибки проверки от сервера ({поле: [текст]}) → {поле: 'текст'} для форм.
export function fieldErrors(data) {
  const errors = {}
  for (const [field, messages] of Object.entries(data ?? {})) {
    errors[field] = Array.isArray(messages) ? messages.join(' ') : String(messages)
  }
  return errors
}

// Добавление записи справочника «на лету»: если такая уже есть (без учёта регистра),
// берём её, а не пытаемся создать дубль.
export function existingByName(list, name) {
  const needle = name.trim().toLowerCase()
  return list.find((item) => item.name.trim().toLowerCase() === needle)
}
