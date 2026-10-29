<template>
  <q-layout>
    <q-page-container>
      <q-page class="flex flex-center q-pa-md login-page">
        <q-card flat bordered class="login-card">
          <q-card-section>
            <div class="text-h6">Вход в систему</div>
            <div class="text-caption text-grey-7">Ветклиника</div>
          </q-card-section>
          <q-form @submit="onSubmit">
            <q-card-section class="q-gutter-md">
              <q-input v-model="username" label="Логин" autofocus autocomplete="username" outlined />
              <q-input
                v-model="password"
                label="Пароль"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                outlined
              >
                <template #append>
                  <q-icon
                    :name="showPassword ? 'visibility_off' : 'visibility'"
                    class="cursor-pointer"
                    @click="showPassword = !showPassword"
                  />
                </template>
              </q-input>
              <div v-if="error" class="text-negative">{{ error }}</div>
            </q-card-section>
            <q-card-actions class="q-px-md q-pb-md">
              <q-btn type="submit" color="primary" label="Войти" class="full-width" :loading="loading" unelevated />
            </q-card-actions>
          </q-form>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '@/session'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')

async function onSubmit() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = 'Введите логин и пароль.'
    return
  }
  loading.value = true
  const { ok, data } = await login(username.value, password.value)
  loading.value = false
  if (!ok) {
    error.value = data?.detail || 'Не удалось войти. Проверьте связь с сервером.'
    return
  }
  router.replace(route.query.next || '/')
}
</script>

<style scoped>
.login-card {
  width: 100%;
  max-width: 380px;
}
</style>
