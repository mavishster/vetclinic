// Кто вошёл в систему и что ему можно. Простое реактивное состояние без лишних библиотек (KISS).
import { reactive } from 'vue'
import { apiGet, apiPost } from './api'
import { applyUiSettings } from './theme'

export const session = reactive({ user: null, loaded: false })

export async function loadMe() {
  const { ok, data } = await apiGet('core/me/')
  session.user = ok ? data : null
  session.loaded = true
  applyUiSettings(session.user?.ui_settings)
}

export async function login(username, password) {
  await apiGet('core/auth/csrf/')
  const result = await apiPost('core/auth/login/', { username, password })
  if (result.ok) await loadMe()
  return result
}

export async function logout() {
  await apiPost('core/auth/logout/')
  session.user = null
  applyUiSettings() // на экране входа — оформление по умолчанию
}

// can('clients.view_species') — есть ли право. Администратору можно всё.
export function can(permission) {
  const user = session.user
  return Boolean(user && (user.is_superuser || user.permissions.includes(permission)))
}
