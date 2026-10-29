<template>
  <div>
    <q-editor ref="editor" :model-value="modelValue" min-height="220px" :toolbar="toolbar"
      :placeholder="placeholder" @update:model-value="emit('update:modelValue', $event)" @keydown="onKeydown" />
    <div class="text-caption text-grey-7 q-mt-xs">
      Наберите <b>@</b> или <b>*</b>, чтобы отметить услугу или товар из прайса — потом они одной кнопкой попадут в счёт.
    </div>

    <q-dialog v-model="pickerOpen" @hide="restoreCaret">
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
            active-class="bg-blue-1" @click="choose(option)">
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
import { apiGet } from '@/api'
import { money } from '@/modules/catalog/money'

defineProps({ modelValue: { type: String, default: '' }, placeholder: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const toolbar = [
  ['bold', 'italic', 'underline', 'strike'],
  ['unordered', 'ordered', 'outdent', 'indent'],
  [{ icon: 'format_size', list: 'no-icons', options: ['p', 'h3', 'h4'] }],
  ['undo', 'redo'],
]

const editor = ref(null)
const pickerOpen = ref(false)
const query = ref('')
const results = ref([])
const active = ref(0)
let pending = null // выбранная позиция — вставляется, когда окно поиска закроется и фокус вернётся

function onKeydown(event) {
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
