<template>
  <q-page padding class="narrow-page">
    <h1 class="text-h5 q-mt-none">{{ session.user.full_name || session.user.username }}</h1>
    <p class="text-grey-7">Логин: {{ session.user.username }}</p>

    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-subtitle1">Оформление</div>
        <div class="text-caption text-grey-7">Только для вас — на любом компьютере, где вы входите в систему.</div>
      </q-card-section>
      <q-card-section class="q-pt-none q-gutter-y-md">
        <q-btn-toggle v-model="ui.theme" no-caps unelevated spread toggle-color="primary" @update:model-value="saveUi"
          :options="[{ label: 'Светлая', value: 'light', icon: 'light_mode' }, { label: 'Тёмная', value: 'dark', icon: 'dark_mode' },
                     { label: 'Как в системе', value: 'auto', icon: 'brightness_auto' }]" />
        <div>
          <div class="text-caption text-grey-8 q-mb-xs">Основной цвет</div>
          <div class="row q-gutter-sm items-center">
            <q-btn v-for="p in PALETTE" :key="p.color" round unelevated size="md" :style="{ background: p.color }"
              :aria-label="p.name" @click="pick(p.color)">
              <q-icon v-if="ui.primary === p.color" name="check" color="white" />
              <q-tooltip>{{ p.name }}</q-tooltip>
            </q-btn>
            <q-input :model-value="ui.primary" type="color" dense outlined style="width: 90px" @change="(e) => pick(e.target.value)">
              <q-tooltip>Свой цвет</q-tooltip>
            </q-input>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered>
      <q-card-section>
        <div class="text-subtitle1">ПИН для подтверждения операций</div>
        <div class="text-body2 text-grey-8 q-mt-xs">
          ПИН подтверждает важные действия: кассовые операции, откаты, удаления.
          4–6 цифр; простые вроде 0000 и 1234 не подойдут.
        </div>
        <q-chip
          :color="session.user.has_pin ? 'positive' : 'grey-5'"
          text-color="white"
          :icon="session.user.has_pin ? 'check' : 'remove'"
          class="q-ml-none q-mt-sm"
        >
          {{ session.user.has_pin ? 'ПИН задан' : 'ПИН не задан' }}
        </q-chip>
      </q-card-section>

      <q-form @submit="onSubmit">
        <q-card-section class="q-gutter-md">
          <q-input v-model="form.password" type="password" label="Текущий пароль" outlined
            autocomplete="current-password" :error="!!errors.password" :error-message="errors.password" />
          <q-input v-model="form.pin" type="password" inputmode="numeric" maxlength="6" label="Новый ПИН"
            outlined autocomplete="off" :error="!!errors.pin" :error-message="errors.pin" />
          <q-input v-model="form.pinRepeat" type="password" inputmode="numeric" maxlength="6"
            label="ПИН ещё раз" outlined autocomplete="off"
            :error="!!errors.pinRepeat" :error-message="errors.pinRepeat" />
        </q-card-section>
        <q-card-actions class="q-px-md q-pb-md">
          <q-btn type="submit" color="primary" unelevated :loading="saving"
            :label="session.user.has_pin ? 'Сменить ПИН' : 'Задать ПИН'" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-page>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { apiPatch, apiPost, fieldErrors } from '@/api'
import { loadMe, session } from '@/session'
import { applyUiSettings, DEFAULT_PRIMARY, PALETTE } from '@/theme'

const $q = useQuasar()
const form = reactive({ password: '', pin: '', pinRepeat: '' })
const errors = ref({})
const saving = ref(false)

// Оформление: меняется сразу и сохраняется в учётной записи.
const ui = reactive({ theme: 'auto', primary: DEFAULT_PRIMARY, ...(session.user.ui_settings || {}) })
async function saveUi() {
  applyUiSettings(ui)
  const { ok, data } = await apiPatch('core/me/ui/', { theme: ui.theme, primary: ui.primary })
  if (!ok) return $q.notify({ type: 'negative', message: Object.values(fieldErrors(data))[0] || 'Не удалось сохранить' })
  session.user.ui_settings = data
}
function pick(color) {
  ui.primary = color
  saveUi()
}

async function onSubmit() {
  errors.value = {}
  if (form.pin !== form.pinRepeat) {
    errors.value = { pinRepeat: 'ПИН не совпадает.' }
    return
  }
  saving.value = true
  const { ok, data } = await apiPost('core/me/pin/', { password: form.password, pin: form.pin })
  saving.value = false
  if (!ok) {
    errors.value = fieldErrors(data)
    return
  }
  Object.assign(form, { password: '', pin: '', pinRepeat: '' })
  await loadMe()
  $q.notify({ type: 'positive', message: 'ПИН сохранён' })
}
</script>
