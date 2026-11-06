// Логотип клиники (Настройки клиники): адрес картинки и значок вкладки браузера.
// Версия меняется при каждой замене логотипа — браузер не покажет старую картинку из кэша.

export const logoUrl = (version) => (version ? `/api/core/clinic/logo/?v=${version}` : null)

export function applyFavicon(version) {
  let link = document.querySelector("link[rel~='icon']")
  if (!version) {
    link?.remove()
    return
  }
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.type = 'image/png'
  link.href = logoUrl(version)
}
