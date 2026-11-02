<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <h1 class="text-h5 q-my-none col-grow">Печатные формы</h1>
      <q-btn v-if="can('core.add_printtemplate')" color="primary" unelevated icon="add" label="Новая форма" @click="open()" />
    </div>
    <p class="text-grey-8">
      Шаблоны документов: счёт, выписка из медкарты, памятка владельцу, этикетка, лист назначений, документы клиенту на подпись.
      Формы вида «Документ клиента (на подпись)» сразу появляются в списке кнопки «На подпись» в карточке клиента.
    </p>
    <q-select v-model="kindFilter" :options="kindOptions" emit-value map-options outlined dense clearable label="Вид" style="max-width: 360px" class="q-mb-md" />

    <q-list bordered separator class="rounded-borders">
      <template v-for="group in groups" :key="group.code">
        <q-item-label header class="text-weight-medium">{{ group.title }}</q-item-label>
        <q-item v-for="t in group.items" :key="t.id" clickable @click="open(t)">
          <q-item-section avatar><q-icon name="description" :color="t.is_active ? 'primary' : 'grey-5'" /></q-item-section>
          <q-item-section>
            <q-item-label :class="{ 'text-grey-6': !t.is_active }">{{ t.name }}</q-item-label>
            <q-item-label v-if="!t.is_active" caption>неактивна</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn flat round dense icon="picture_as_pdf" :href="`/api/core/print-templates/${t.id}/sample/`" target="_blank" @click.stop>
              <q-tooltip>PDF на примере</q-tooltip>
            </q-btn>
          </q-item-section>
        </q-item>
      </template>
      <q-item v-if="!groups.length"><q-item-section class="text-grey-7">Форм нет</q-item-section></q-item>
    </q-list>

    <!-- Редактор: слева текст и подсказки, справа — живой предпросмотр на примере данных -->
    <q-dialog v-model="editorOpen" maximized>
      <q-card class="column no-wrap">
        <q-card-section class="row items-center q-py-sm">
          <div class="text-h6 col">{{ form.id ? form.name : 'Новая печатная форма' }}</div>
          <q-btn v-if="form.id" flat icon="content_copy" label="Копия" @click="duplicate"><q-tooltip>Сделать новую форму на основе этой</q-tooltip></q-btn>
          <q-btn v-if="form.id" flat icon="picture_as_pdf" label="PDF" :href="`/api/core/print-templates/${form.id}/sample/`" target="_blank" />
          <q-btn flat label="Закрыть" v-close-popup />
          <q-btn v-if="canEdit" color="primary" unelevated icon="save" label="Сохранить" :loading="saving" @click="save" />
        </q-card-section>
        <q-separator />
        <div class="row col no-wrap" style="min-height: 0">
          <div class="col-12 col-md-6 column no-wrap q-pa-md" style="overflow: auto">
            <div class="row q-col-gutter-sm">
              <q-input v-model="form.name" outlined dense label="Название *" class="col-12 col-sm-7" :readonly="!canEdit" />
              <q-select v-model="form.kind" :options="kindOptions" emit-value map-options outlined dense label="Вид *" class="col-12 col-sm-5"
                :readonly="!canEdit || !!form.id" @update:model-value="refresh" />
            </div>
            <q-checkbox v-model="form.is_active" label="Активна" dense class="q-my-sm" :disable="!canEdit" />

            <div class="row items-center q-gutter-xs q-mb-xs">
              <span class="text-caption text-grey-8 q-mr-sm">Вставить:</span>
              <q-btn v-for="s in SNIPPETS" :key="s.label" outline dense no-caps size="sm" :label="s.label" :disable="!canEdit" @click="insert(s.text)">
                <q-tooltip>{{ s.hint }}</q-tooltip>
              </q-btn>
            </div>
            <q-input ref="bodyInput" v-model="form.body" type="textarea" outlined input-class="code" :input-style="{ minHeight: '320px' }"
              :readonly="!canEdit" :error="!!error" :error-message="error" @update:model-value="refresh" />

            <q-expansion-item default-opened dense icon="data_object" label="Подстановки этого вида — нажмите, чтобы вставить" header-class="text-weight-medium">
              <q-list dense>
                <q-item v-for="(text, name) in variables" :key="name" clickable :disable="!canEdit" @click="insertVariable(name)">
                  <q-item-section><code>{{ `\{\{ ${name} \}\}` }}</code></q-item-section>
                  <q-item-section class="text-grey-8">{{ text }}</q-item-section>
                </q-item>
              </q-list>
            </q-expansion-item>
            <q-expansion-item dense icon="help_outline" label="Как писать шаблон" header-class="text-weight-medium">
              <div class="q-pa-sm text-body2 help">
                <p><b>Подстановка</b> — имя в двойных фигурных скобках: <code v-pre>{{ client.full_name }}</code> → «Иванова Анна Петровна».</p>
                <p><b>Форматы</b> — через вертикальную черту:</p>
                <ul><li v-for="(text, name) in filters" :key="name"><code>{{ text }}</code></li></ul>
                <p><b>Условие</b> — показать текст, только если данные есть:<br>
                  <code v-pre>{% if client.phones %}телефон {{ client.phones }}{% endif %}</code></p>
                <p><b>Список</b> — повторить для каждого элемента (например, питомцев):<br>
                  <code v-pre>{% for p in pets %}{{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}</code></p>
                <p><b>Оформление</b> — обычные теги HTML: <code>&lt;h2&gt;</code> заголовок, <code>&lt;p&gt;</code> абзац,
                  <code>&lt;b&gt;</code> жирный, <code>&lt;br&gt;</code> перенос строки, <code>&lt;table&gt;</code> таблица.
                  Выравнивание: <code>&lt;p style="text-align:center;"&gt;</code>.</p>
                <p>Ошибка в шаблоне видна сразу под текстом, а справа — как документ выглядит на примере данных.
                  Подпись клиента и сведения о подписании система добавляет в конец документа сама.</p>
              </div>
            </q-expansion-item>
          </div>
          <div class="col-md-6 gt-sm column no-wrap q-pa-md preview-side">
            <div class="text-caption text-grey-8 q-mb-xs">Предпросмотр на примере данных</div>
            <iframe class="preview col" :srcdoc="previewHtml" sandbox="" title="Предпросмотр" />
          </div>
        </div>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
// Печатные формы: список по видам и редактор с подсказками и живым предпросмотром.
import { computed, nextTick, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiGet, apiPatch, apiPost, fieldErrors } from '@/api'
import { can } from '@/session'

const $q = useQuasar()
const templates = ref([])
const kinds = ref([])
const filters = ref({})
const kindFilter = ref(null)
const editorOpen = ref(false)
const form = ref({})
const error = ref('')
const saving = ref(false)
const previewHtml = ref('')
const bodyInput = ref(null)
const canEdit = computed(() => can(form.value.id ? 'core.change_printtemplate' : 'core.add_printtemplate'))
const kindOptions = computed(() => kinds.value.map((k) => ({ value: k.code, label: k.title })))
const variables = computed(() => kinds.value.find((k) => k.code === form.value.kind)?.variables ?? {})
const groups = computed(() =>
  kinds.value
    .filter((k) => !kindFilter.value || k.code === kindFilter.value)
    .map((k) => ({ code: k.code, title: k.title, items: templates.value.filter((t) => t.kind === k.code) }))
    .filter((g) => g.items.length),
)

const SNIPPETS = [
  { label: 'Заголовок', text: '<h2 style="text-align:center;">Заголовок</h2>\n', hint: 'Заголовок по центру' },
  { label: 'Абзац', text: '<p>Текст абзаца.</p>\n', hint: 'Новый абзац' },
  { label: 'Дата справа', text: '<p style="text-align:right;">{{ today|date }}</p>\n', hint: 'Сегодняшняя дата по правому краю' },
  { label: 'Если есть…', text: '{% if client.phones %}телефон {{ client.phones }}{% endif %}', hint: 'Показать текст, только если данные заполнены' },
  { label: 'Питомцы списком', text: '{% for p in pets %}{{ p.name }} ({{ p.species }}){% if not loop.last %}, {% endif %}{% endfor %}', hint: 'Все питомцы клиента через запятую' },
  { label: 'Подпись клиники', text: '<p style="margin-top:24px;">{{ clinic.name }}{% if clinic.address %}, {{ clinic.address }}{% endif %}</p>\n', hint: 'Название и адрес клиники' },
]

async function load() {
  const [list, meta] = await Promise.all([apiGet('core/print-templates/'), apiGet('core/print-templates/kinds/')])
  templates.value = list.data?.results ?? list.data ?? []
  kinds.value = meta.data?.kinds ?? []
  filters.value = meta.data?.filters ?? {}
}

function open(template = null) {
  error.value = ''
  form.value = template
    ? { ...template }
    : { name: '', kind: kindFilter.value || 'client_document', body: '<h2 style="text-align:center;">Название документа</h2>\n<p>Я, {{ client.full_name }}, …</p>\n<p style="text-align:right;">{{ today|date }}</p>\n', is_active: true }
  editorOpen.value = true
  refresh()
}

function duplicate() {
  form.value = { ...form.value, id: undefined, name: `${form.value.name} (копия)` }
  $q.notify({ type: 'info', message: 'Это копия — поменяйте название и сохраните' })
}

// Вставка в место курсора в тексте шаблона.
async function insert(text) {
  const area = bodyInput.value?.getNativeElement?.() || bodyInput.value?.$el?.querySelector('textarea')
  const body = form.value.body || ''
  const at = area ? area.selectionStart : body.length
  const end = area ? area.selectionEnd : body.length
  form.value.body = body.slice(0, at) + text + body.slice(end)
  refresh()
  await nextTick()
  if (area) {
    area.focus()
    area.selectionStart = area.selectionEnd = at + text.length
  }
}
// Списки (питомцы, назначения, строки счёта…) вставляются сразу циклом по элементам,
// а не одной подстановкой: в описании такого списка после двоеточия перечислены поля.
function insertVariable(name) {
  const description = variables.value[name] || ''
  const fields = description.includes(':') && !name.includes('.') ? description.split(':')[1].split(',').map((f) => f.trim()).filter(Boolean) : []
  if (!fields.length) return insert(`{{ ${name} }}`)
  insert(`{% for item in ${name} %}{{ item.${fields[0]} }}{% if not loop.last %}, {% endif %}{% endfor %}`)
}

let timer = null
function refresh() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    if (!form.value.kind) return
    const { ok, data } = await apiPost('core/print-templates/preview/', { kind: form.value.kind, body: form.value.body || '' })
    if (ok) {
      previewHtml.value = data.html
      error.value = ''
    } else error.value = Object.values(fieldErrors(data))[0] || 'Ошибка в шаблоне'
  }, 500)
}

async function save() {
  saving.value = true
  const body = { name: form.value.name, kind: form.value.kind, body: form.value.body, is_active: form.value.is_active }
  const { ok, data } = form.value.id
    ? await apiPatch(`core/print-templates/${form.value.id}/`, body)
    : await apiPost('core/print-templates/', body)
  saving.value = false
  if (!ok) return (error.value = Object.values(fieldErrors(data))[0] || 'Не удалось сохранить')
  form.value = { ...data }
  $q.notify({ type: 'positive', message: 'Сохранено' })
  load()
}

onMounted(load)
</script>

<style scoped>
:deep(.code) {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
}
.preview {
  border: 1px solid rgba(127, 127, 127, 0.3);
  border-radius: 6px;
  width: 100%;
  background: #fff;
}
.preview-side {
  border-left: 1px solid rgba(127, 127, 127, 0.2);
}
.help code {
  font-size: 12px;
  background: rgba(127, 127, 127, 0.12);
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
