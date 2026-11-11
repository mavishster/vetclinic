// Разделы подбора препаратов: по названию, аналоги по действующему веществу, та же группа.
export const SECTION_TITLES = {
  name: '',
  substance: 'То же действующее вещество',
  group: 'Та же группа препаратов',
}

// Заголовок показывается только у первой позиции раздела.
export function withHeaders(rows) {
  let previous = null
  return rows.map((row) => {
    const section = row.section || 'name'
    const header = section !== previous ? SECTION_TITLES[section] || '' : ''
    previous = section
    return { ...row, header }
  })
}
