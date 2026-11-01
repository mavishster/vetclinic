<template>
  <div>
    <q-editor ref="editor" :model-value="modelValue" min-height="220px" :toolbar="toolbar"
      :placeholder="placeholder" @update:model-value="onChange" @keydown="onKeydown">
      <template #templates>
        <q-btn-dropdown v-if="visitId" dense flat no-caps size="sm" icon="article" label="Шаблон" @show="loadTemplates"
          @before-show="editor.caret.save()">
          <q-list dense style="min-width: 260px; max-width: 360px">
            <q-item v-for="t in templates" :key="t.id" v-close-popup clickable @click="insertTemplate(t)">
              <q-item-section>
                <q-item-label>{{ t.name }}</q-item-label>
                <q-item-label caption>{{ [t.is_personal ? 'личный' : '', t.purpose_name].filter(Boolean).join(' · ') }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="!templates.length"><q-item-section class="text-grey-7">Шаблонов для этой вкладки нет</q-item-section></q-item>
            <q-separator />
            <q-item v-close-popup clickable @click="saveAsTemplate">
              <q-item-section avatar><q-icon name="bookmark_add" /></q-item-section>
              <q-item-section>Сохранить текст как мой шаблон</q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </template>
    </q-editor>
    <div class="text-caption text-grey-7 q-mt-xs">
      Наберите <b>@</b> или <b>*</b>, чтобы отметить услугу или товар из прайса — потом они одной кнопкой попадут в счёт.
      <template v-if="visitId">«Шаблон» вставит готовый текст; <b>Tab</b> — к следующему полю для заполнения.</template>
    </div>

    <!-- Без анимации: окно получает фокус сразу, и буквы, набранные после «@», не теряются. -->
    <q-dialog v-model="pickerOpen" :transition-duration="0" @hide="restoreCaret">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="q-pb-none">
          <q-input v-model="query" autofocus outlined dense placeholder="Услуга или товар…" debounce="250"
            @update:model-value="search" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="choose(results[active])">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </q-card-section>
        <q-list dense class="q-pa-sm" style="max-height: 360px; overflow: auto">
          <q-item v-for="(option, i) in results" :key="option.id" clickable :active="i === active"
            active-class="row-highlight-primary" @click="choose(option)">
            <q-item-section>{{ option.label }}</q-item-section>
            <q-item-section side>{{ option.price ? money(option.price) : '' }}</q-item-section>
          </q-item>
          <q-item v-if="query.length >= 2 && !results.length"><q-item-section class="text-grey-7">Не найдено</q-item-section></q-item>
        </q-list>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
// Текст медкарты: оформление + отметки позиций прайса через «@» (или «*», как в VetManager).
// Отметка — неизменяемый фрагмент с id единицы товара; сервер собирает их в позиции записи.
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPost } from '@/api'
import { money } from '@/modules/catalog/money'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  visitId: { type: String, default: null }, // для шаблонов: подставить данные этой записи
  section: { type: String, default: 'treatment' }, // вкладка: treatment | recommendations
  purpose: { type: String, default: null }, // цель приёма — её шаблоны первыми
})
const emit = defineEmits(['update:modelValue'])
const $q = useQuasar()
const toolbar = [
  ['bold', 'italic', 'underline', 'strike'],
  ['unordered', 'ordered', 'outdent', 'indent'],
  [{ icon: 'format_size', list: 'no-icons', options: ['p', 'h3', 'h4'] }],
  ['undo', 'redo'],
  ['templates'],
]

// --- Шаблоны: вставка с подстановкой данных записи, поля [___], переход по Tab ---
const templates = ref([])
async function loadTemplates() {
  const params = new URLSearchParams({ section: props.section })
  if (props.purpose) params.set('purpose', props.purpose)
  templates.value = (await apiGet(`medical/text-templates/?${params}`)).data ?? []
}

async function insertTemplate(template) {
  const { ok, data } = await apiPost(`medical/visits/${props.visitId}/render-template/`, { template: template.id })
  if (!ok) return $q.notify({ type: 'negative', message: 'Не удалось вставить шаблон' })
  editor.value.focus()
  editor.value.caret.restore()
  inserting = true // вставка — не ввод: поля шаблона не трогаем
  editor.value.runCmd('insertHTML', data.html)
  setTimeout(() => {
    inserting = false
    goToField(1, true)
  }, 0)
}
let inserting = false

function fieldsInEditor() {
  return [...editor.value.getContentEl().querySelectorAll('.fill-field')]
}

// Выделить следующее (step = 1) или предыдущее (−1) поле для заполнения; first — первое в тексте.
function goToField(step, first = false) {
  const fields = fieldsInEditor()
  if (!fields.length) return false
  const selection = window.getSelection()
  let target = fields[0]
  if (!first && selection.rangeCount) {
    const caret = selection.getRangeAt(0)
    const inside = fields.find((f) => f.contains(caret.startContainer))
    const index = inside ? fields.indexOf(inside) : -1
    if (index >= 0) target = fields[(index + step + fields.length) % fields.length]
    else {
      const after = fields.filter((f) => caret.comparePoint(f, 0) > 0)
      const before = fields.filter((f) => caret.comparePoint(f, 0) < 0)
      target = step > 0 ? after[0] || fields[0] : before[before.length - 1] || fields[fields.length - 1]
    }
  }
  const range = document.createRange()
  range.selectNodeContents(target)
  selection.removeAllRanges()
  selection.addRange(range)
  target.scrollIntoView({ block: 'nearest' })
  return true
}

function onChange(value) {
  emit('update:modelValue', value)
  unwrapFilledField()
}

// Поле заполнили — убираем подсветку: оно становится обычным текстом.
function unwrapFilledField() {
  if (inserting) return
  const node = window.getSelection()?.anchorNode
  const element = node && (node.nodeType === 1 ? node : node.parentElement)
  const field = element?.closest?.('.fill-field')
  if (!field) return
  const text = document.createTextNode(field.textContent)
  field.replaceWith(text)
  const range = document.createRange()
  range.setStart(text, text.length)
  range.collapse(true)
  window.getSelection().removeAllRanges()
  window.getSelection().addRange(range)
  emit('update:modelValue', editor.value.getContentEl().innerHTML)
}

function saveAsTemplate() {
  $q.dialog({
    title: 'Сохранить как мой шаблон', message: 'Название шаблона', prompt: { model: '', type: 'text' },
    cancel: { label: 'Отмена', flat: true }, ok: { label: 'Сохранить', color: 'primary', unelevated: true },
  }).onOk(async (name) => {
    const { ok } = await apiPost('medical/text-templates/', {
      name, section: props.section, purpose: props.purpose, body_html: props.modelValue, personal: true,
    })
    $q.notify(ok ? { type: 'positive', message: 'Шаблон сохранён — он в списке «Шаблон»' } : { type: 'negative', message: 'Не удалось сохранить шаблон' })
  })
}

const editor = ref(null)
const pickerOpen = ref(false)
const query = ref('')
const results = ref([])
const active = ref(0)
let pending = null // выбранная позиция — вставляется, когда окно поиска закроется и фокус вернётся

function onKeydown(event) {
  if (event.key === 'Tab' && fieldsInEditor().length) {
    event.preventDefault()
    goToField(event.shiftKey ? -1 : 1)
    return
  }
  if (event.key !== '@' && event.key !== '*') return
  event.preventDefault()
  editor.value.caret.save()
  query.value = ''
  results.value = []
  pending = null
  pickerOpen.value = true
}

async function search(text) {
  active.value = 0
  if (!text || text.trim().length < 2) return (results.value = [])
  const { data } = await apiGet(`catalog/items/?kind=goods,service&active=true&page_size=15&search=${encodeURIComponent(text)}`)
  results.value = (data?.results ?? []).flatMap((item) =>
    item.units.filter((u) => u.for_sale).map((u) => ({
      id: u.id, label: `${item.name} (${u.unit_name})`, price: u.current_price, name: item.name, unit: u.unit_name,
    })),
  )
}

const move = (step) => (active.value = Math.min(Math.max(active.value + step, 0), results.value.length - 1))
const escape = (text) => text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

function choose(option) {
  if (!option) return
  pending = option
  pickerOpen.value = false
}

// Окно закрылось: возвращаем курсор в текст и, если позиция выбрана, вставляем отметку.
function restoreCaret() {
  editor.value.focus()
  editor.value.caret.restore()
  if (pending) {
    editor.value.runCmd(
      'insertHTML',
      `<span class="item-mention" data-item-unit="${pending.id}" contenteditable="false">${escape(pending.label)}</span>&nbsp;`,
    )
    pending = null
  }
}
</script>

<style>
.fill-field {
  background: rgba(181, 131, 42, 0.22);
  border-bottom: 1px dashed #b5832a;
  border-radius: 3px;
  padding: 0 3px;
}
.item-mention {
  background: rgba(36, 86, 106, 0.12);
  color: #24566a;
  border-radius: 4px;
  padding: 0 4px;
  white-space: nowrap;
}
body.body--dark .item-mention {
  color: #9cc9da;
}
</style>
