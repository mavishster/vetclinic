<template>
  <q-layout view="hHh Lpr lFf">
    <q-header class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" aria-label="Меню" @click="drawerOpen = !drawerOpen" />
        <q-toolbar-title>{{ clinicTitle }}</q-toolbar-title>
        <!-- Стационар: напоминания о назначениях моим пациентам -->
        <TasksBell v-if="can('inpatient.view_hospitalization')" />
        <!-- Отделения: остатки не внесены, давно не было выдачи, ниже нормы -->
        <DepartmentAlertsBell />
        <q-btn flat no-caps icon="account_circle" :label="$q.screen.gt.xs ? session.user?.short_name || session.user?.username : ''">
          <q-menu anchor="bottom right" self="top right">
            <q-list style="min-width: 200px">
              <q-item clickable v-close-popup to="/profile">
                <q-item-section avatar><q-icon name="person" /></q-item-section>
                <q-item-section>Профиль и ПИН</q-item-section>
              </q-item>
              <q-separator />
              <q-item clickable v-close-popup @click="onLogout">
                <q-item-section avatar><q-icon name="logout" /></q-item-section>
                <q-item-section>Выйти</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawerOpen" show-if-above bordered :width="260">
      <q-list padding>
        <template v-for="(section, index) in visibleSections" :key="index">
          <!-- Сворачиваемый раздел (Склад, Справочники): щелчок по заголовку -->
          <q-expansion-item v-if="section.collapsible" :model-value="isOpen(section)" :label="section.title" :icon="section.icon"
            header-class="text-weight-medium" :content-inset-level="0.3" @update:model-value="toggle(section, $event)">
            <q-item v-for="item in section.items" :key="item.title" :to="item.to" clickable exact dense
              active-class="text-primary text-weight-medium">
              <q-item-section avatar><q-icon :name="item.icon" /></q-item-section>
              <q-item-section><q-item-label>{{ item.title }}</q-item-label></q-item-section>
            </q-item>
          </q-expansion-item>
          <template v-else>
          <q-item-label v-if="section.title" header class="q-pb-xs">{{ section.title }}</q-item-label>
          <q-item
            v-for="item in section.items"
            :key="item.title"
            :to="item.to"
            :disable="!item.to"
            clickable
            exact
            active-class="text-primary text-weight-medium"
          >
            <q-item-section avatar>
              <q-icon :name="item.icon" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ item.title }}</q-item-label>
              <q-item-label v-if="!item.to" caption>Этап {{ item.stage }}</q-item-label>
            </q-item-section>
          </q-item>
          </template>
        </template>
      </q-list>
    </q-drawer>

    <q-page-container>
      <!-- key: разные экраны на одном компоненте (справочники) пересоздаются при переходе -->
      <router-view :key="$route.path" />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import TasksBell from '@/modules/inpatient/TasksBell.vue'
import DepartmentAlertsBell from '@/modules/inventory/DepartmentAlertsBell.vue'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import sections from '@/modules/registry'
import { can, logout, session } from '@/session'

const drawerOpen = ref(false)
const router = useRouter()
const clinicTitle = computed(() => session.user?.clinic || 'Ветклиника')

// Пункты без права perm скрываются; пустые разделы — тоже.
const visibleSections = computed(() =>
  sections
    .map((section) => ({ ...section, items: section.items.filter((i) => !i.perm || can(i.perm)) }))
    .filter((section) => section.items.length),
)

// Свёрнут / развёрнут раздел — запоминается в браузере; раздел текущей страницы открыт всегда.
const OPEN_KEY = 'menu.open'
const saved = ref(readSaved())
function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(OPEN_KEY) || '{}')
  } catch {
    return {}
  }
}
const route = useRoute()
const hasCurrent = (section) => section.items.some((i) => i.to && route.path.startsWith(i.to))
const isOpen = (section) => saved.value[section.title] ?? (section.expanded || hasCurrent(section))
function toggle(section, value) {
  saved.value = { ...saved.value, [section.title]: value }
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify(saved.value))
  } catch {
    // без хранилища браузера — просто не запоминаем
  }
}

async function onLogout() {
  await logout()
  router.push('/login')
}
</script>
