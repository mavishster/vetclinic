<template>
  <q-page padding class="narrow-page">
    <h1 class="text-h5 q-mt-none">Настройки клиники</h1>
    <q-form @submit="save">
      <q-card flat bordered class="q-mb-md">
        <q-card-section class="text-subtitle1">Клиника</q-card-section>
        <q-card-section class="q-pt-none q-gutter-y-sm">
          <q-input v-model="form.name" outlined dense label="Название" hint="Печатается в счетах, выписках, документах на подпись" :readonly="!canEdit" />
          <q-input v-model="form.address" outlined dense label="Адрес" :readonly="!canEdit" />
          <q-input v-model="form.phone" outlined dense label="Телефон" :readonly="!canEdit" />
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1">Логотип</div>
          <div class="text-caption text-grey-7">
            Показывается в шапке системы, на экране входа, во вкладке браузера и в печатных формах — там, где в шаблон
            вставлено <code v-pre>{{ clinic.logo }}</code>. PNG (лучше с прозрачным фоном), JPEG, WebP или GIF до 5 МБ;
            картинка уменьшится до 600 px.
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none row items-center q-col-gutter-md">
          <div class="col-auto">
            <div class="logo-preview row flex-center">
              <img v-if="logoSrc && !logoBroken" :src="logoSrc" alt="Логотип" @error="logoBroken = true" />
              <span v-else class="text-grey-6 text-caption">Логотипа нет</span>
            </div>
          </div>
          <div v-if="canEdit" class="col q-gutter-sm">
            <q-file v-model="logoFile" accept="image/png,image/jpeg,image/webp,image/gif" outlined dense clearable
              label="Выбрать картинку" :error="!!errors.file" :error-message="errors.file" @update:model-value="uploadLogo">
              <template #prepend><q-icon name="image" /></template>
            </q-file>
            <q-btn v-if="logoSrc" flat color="negative" icon="delete" label="Убрать логотип" :loading="logoBusy" @click="removeLogo" />
          </div>
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1">Скидки в счёте</div>
          <div class="text-caption text-grey-7">
            Больше этих процентов скидку в строке счёта поставить нельзя. Кроме того, цена со скидкой не может быть ниже
            себестоимости — система не даст применить такую скидку.
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none row q-col-gutter-sm">
          <q-input v-model="form.max_discount_goods" type="number" step="0.5" min="0" max="100" outlined dense suffix="%"
            label="Максимальная скидка на товары" class="col-12 col-sm-6" :readonly="!canEdit" :error="!!errors.max_discount_goods"
            :error-message="errors.max_discount_goods" />
          <q-input v-model="form.max_discount_services" type="number" step="0.5" min="0" max="100" outlined dense suffix="%"
            label="Максимальная скидка на услуги" class="col-12 col-sm-6" :readonly="!canEdit" :error="!!errors.max_discount_services"
            :error-message="errors.max_discount_services" />
          <div class="col-12 text-caption text-grey-7">Комбинации — по составу: товары в них — по лимиту товаров, услуги — по лимиту услуг.</div>
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1">Отделения: выдача и внесение остатков</div>
          <div class="text-caption text-grey-7">
            По этим срокам система предупреждает главного администратора (особое право «Отделения: нормы, контроль…») и
            ответственного за отделение — на главной и значком в шапке. 0 — не напоминать.
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none row q-col-gutter-sm">
          <q-input v-model.number="form.department_issue_days" type="number" step="1" min="0" max="365" outlined dense suffix="дн."
            label="Выдавать не реже, чем раз в" class="col-12 col-sm-4" :readonly="!canEdit" :error="!!errors.department_issue_days"
            :error-message="errors.department_issue_days" />
          <q-input v-model.number="form.department_count_from_days" type="number" step="1" min="0" max="365" outlined dense suffix="дн."
            label="Внести остатки — через" hint="после выдачи: «пора внести»" class="col-6 col-sm-4" :readonly="!canEdit"
            :error="!!errors.department_count_from_days" :error-message="errors.department_count_from_days" />
          <q-input v-model.number="form.department_count_due_days" type="number" step="1" min="0" max="365" outlined dense suffix="дн."
            label="…и не позже" hint="после выдачи: «не внесены»" class="col-6 col-sm-4" :readonly="!canEdit"
            :error="!!errors.department_count_due_days" :error-message="errors.department_count_due_days" />
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1">Стационар: QR-этикетка пациента</div>
          <div class="text-caption text-grey-7">
            Этикетку печатают на листе А4 и вырезают по пунктиру, клеят на клетку. Сканируют камерой телефона:
            откроется карточка пациента (нужны вход и право на стационар). В код зашита только ссылка.
          </div>
        </q-card-section>
        <q-card-section class="q-pt-none row q-col-gutter-sm">
          <q-input v-model="form.qr_base_url" outlined dense class="col-12" :readonly="!canEdit"
            label="Адрес системы для QR-кодов" placeholder="http://192.168.0.10"
            hint="Адрес, по которому телефоны открывают систему в сети клиники. Лучше постоянный: при смене адреса старые этикетки перестанут открываться."
            :error="!!errors.qr_base_url" :error-message="errors.qr_base_url" />
          <q-input v-model.number="form.qr_size_mm" type="number" step="1" min="15" max="120" outlined dense suffix="мм"
            label="Размер QR-кода" class="col-12 col-sm-4" :readonly="!canEdit" :error="!!errors.qr_size_mm"
            :error-message="errors.qr_size_mm" />
          <q-input v-model.number="form.qr_label_width_mm" type="number" step="1" min="40" max="200" outlined dense suffix="мм"
            label="Ширина этикетки" class="col-6 col-sm-4" :readonly="!canEdit" :error="!!errors.qr_label_width_mm"
            :error-message="errors.qr_label_width_mm" />
          <q-input v-model.number="form.qr_label_height_mm" type="number" step="1" min="40" max="200" outlined dense suffix="мм"
            label="Высота этикетки" class="col-6 col-sm-4" :readonly="!canEdit" :error="!!errors.qr_label_height_mm"
            :error-message="errors.qr_label_height_mm" />
          <div class="col-12 text-caption text-grey-7">
            На листе А4 помещается {{ perSheet }} эт. Поля листа — по 5 мм.
          </div>
          <div class="col-12">
            <div class="text-weight-medium q-mb-xs">Что печатать над QR-кодом (порядок — стрелками)</div>
            <q-list bordered separator dense class="rounded-borders">
              <q-item v-for="row in qrRows" :key="row.code" dense>
                <q-item-section side>
                  <q-checkbox :model-value="row.on" dense :disable="!canEdit" @update:model-value="toggleQr(row.code)" />
                </q-item-section>
                <q-item-section :class="row.on ? '' : 'text-grey-6'">{{ row.label }}</q-item-section>
                <q-item-section v-if="canEdit && row.on" side>
                  <div class="row no-wrap">
                    <q-btn flat round dense size="sm" icon="arrow_upward" :disable="row.index === 0" @click="moveQr(row.code, -1)" />
                    <q-btn flat round dense size="sm" icon="arrow_downward" :disable="row.index === form.qr_fields.length - 1" @click="moveQr(row.code, 1)" />
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
            <div v-if="errors.qr_fields" class="text-negative text-caption">{{ errors.qr_fields }}</div>
          </div>
        </q-card-section>
      </q-card>
      <q-btn v-if="canEdit" type="submit" color="primary" unelevated icon="save" label="Сохранить" :loading="saving" />
    </q-form>
  </q-page>
</template>

<script setup>
// Настройки клиники: реквизиты для печатных форм, предельные скидки в счёте,
// сроки выдачи и внесения остатков в отделениях (предупреждения).
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiDelete, apiGet, apiPatch, apiUpload, fieldErrors } from '@/api'
import { can, session } from '@/session'
import { logoUrl } from './logo'

const $q = useQuasar()
const canEdit = can('core.change_clinic')
const form = ref({})
const errors = ref({})
const saving = ref(false)
const logoFile = ref(null)
const logoBusy = ref(false)
// Файл логотипа не открылся — показываем «Логотипа нет», а не битую картинку.
const logoBroken = ref(false)
const logoSrc = computed(() => logoUrl(form.value.logo_version))

// Логотип сохраняется сразу при выборе файла; шапка и значок вкладки обновятся сами.
function logoChanged(data) {
  form.value.logo_version = data.logo_version
  if (session.user) session.user.clinic_logo = data.logo_version
}

async function uploadLogo(file) {
  if (!file) return
  errors.value = {}
  logoBusy.value = true
  const body = new FormData()
  body.append('file', file)
  const { ok, data } = await apiUpload('core/clinic/logo/', body)
  logoBusy.value = false
  logoBroken.value = false
  logoFile.value = null
  if (!ok) return (errors.value = fieldErrors(data))
  logoChanged(data)
  $q.notify({ type: 'positive', message: 'Логотип сохранён' })
}

async function removeLogo() {
  logoBusy.value = true
  const { ok, data } = await apiDelete('core/clinic/logo/')
  logoBusy.value = false
  logoBroken.value = false
  if (ok) logoChanged(data)
}

// QR-этикетка: поля из перечня системы; выбранные — в заданном порядке, остальные — ниже.
const qrCatalogue = ref([])
const qrRows = computed(() => {
  const chosen = form.value.qr_fields ?? []
  const label = (code) => qrCatalogue.value.find((f) => f.code === code)?.label
  const on = chosen.filter(label).map((code, index) => ({ code, label: label(code), on: true, index }))
  const off = qrCatalogue.value.filter((f) => !chosen.includes(f.code)).map((f) => ({ ...f, on: false }))
  return [...on, ...off]
})
const perSheet = computed(() => {
  const w = Number(form.value.qr_label_width_mm) || 95
  const h = Number(form.value.qr_label_height_mm) || 140
  return Math.max(Math.floor(200 / w), 1) * Math.max(Math.floor(287 / h), 1)
})

function toggleQr(code) {
  const chosen = form.value.qr_fields ?? []
  form.value.qr_fields = chosen.includes(code) ? chosen.filter((c) => c !== code) : [...chosen, code]
}

function moveQr(code, step) {
  const list = [...form.value.qr_fields]
  const from = list.indexOf(code)
  const to = from + step
  if (to < 0 || to >= list.length) return
  list.splice(to, 0, list.splice(from, 1)[0])
  form.value.qr_fields = list
}

async function save() {
  errors.value = {}
  saving.value = true
  const { ok, data } = await apiPatch('core/clinic/', form.value)
  saving.value = false
  if (!ok) return (errors.value = fieldErrors(data))
  form.value = data
  $q.notify({ type: 'positive', message: 'Настройки сохранены' })
}

onMounted(async () => {
  form.value = (await apiGet('core/clinic/')).data ?? {}
  const fields = await apiGet('inpatient/qr-fields/')
  qrCatalogue.value = fields.ok && Array.isArray(fields.data) ? fields.data : []
})
</script>

<style scoped>
.logo-preview {
  width: 180px;
  height: 90px;
  border: 1px dashed rgba(128, 128, 128, 0.5);
  border-radius: 6px;
  background: #fff;
}
.logo-preview img {
  max-width: 170px;
  max-height: 80px;
  object-fit: contain;
}
</style>
