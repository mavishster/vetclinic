// Расклад блоков на экране: что показывать, в каком столбце и в каком порядке.
// Хранится у каждого сотрудника в его настройках — врач и оператор видят своё.
import { reactive } from 'vue'
import { apiPatch } from '@/api'
import { session } from '@/session'

// Заготовки под роли: выбрал — и готово, без перетаскивания.
export const PRESETS = {
  doctor: {
    title: 'Для врача',
    hint: 'Сверху питомцы и медкарты, счета — ниже',
  },
  operator: {
    title: 'Для оператора',
    hint: 'Сверху счета и баланс, медкарты — ниже',
  },
}

export function useLayout(screen, blocks, presets) {
  const saved = session.user?.ui_settings?.layouts?.[screen]
  const state = reactive({
    blocks: normalize(saved?.blocks, blocks),
    preset: saved?.preset || '',
  })

  // Блоки одного столбца по порядку; скрытые не показываются.
  const column = (name) => state.blocks.filter((b) => b.column === name && b.visible)

  function move(block, direction) {
    const same = state.blocks.filter((b) => b.column === block.column)
    const index = same.indexOf(block)
    const target = same[index + direction]
    if (!target) return
    const from = state.blocks.indexOf(block)
    const to = state.blocks.indexOf(target)
    state.blocks.splice(to, 0, ...state.blocks.splice(from, 1))
    save()
  }

  function toggle(block) {
    block.visible = !block.visible
    save()
  }

  function moveToColumn(block, name) {
    block.column = name
    save()
  }

  function applyPreset(name) {
    const preset = presets?.[name]
    if (!preset) return
    state.blocks = normalize(preset.blocks, blocks)
    state.preset = name
    save()
  }

  function reset() {
    state.blocks = normalize(null, blocks)
    state.preset = ''
    save()
  }

  async function save() {
    const layouts = { ...(session.user?.ui_settings?.layouts || {}) }
    layouts[screen] = {
      preset: state.preset,
      blocks: state.blocks.map(({ name, column, visible }) => ({ name, column, visible })),
    }
    const settings = { ...(session.user?.ui_settings || {}), layouts }
    if (session.user) session.user.ui_settings = settings
    await apiPatch('core/me/ui/', { layouts })
  }

  return { state, column, move, toggle, moveToColumn, applyPreset, reset }
}

// Сохранённый расклад + блоки, которых тогда ещё не было (появились с обновлением).
function normalize(saved, blocks) {
  if (!Array.isArray(saved)) saved = []
  const byName = new Map(blocks.map((b) => [b.name, b]))
  const result = []
  for (const row of saved || []) {
    const block = byName.get(row.name)
    if (!block) continue // блок убрали из системы
    result.push({ ...block, column: row.column ?? block.column, visible: row.visible ?? true })
    byName.delete(row.name)
  }
  for (const block of byName.values()) result.push({ ...block, visible: true })
  return result
}
