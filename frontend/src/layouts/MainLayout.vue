<template>
  <q-layout view="hHh Lpr lFf">
    <q-header class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" aria-label="Меню" @click="drawerOpen = !drawerOpen" />
        <q-toolbar-title>Ветклиника</q-toolbar-title>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawerOpen" show-if-above bordered :width="260">
      <q-list padding>
        <q-item
          v-for="module in modules"
          :key="module.title"
          :to="module.to"
          :disable="!module.to"
          clickable
          exact
          active-class="text-primary text-weight-medium"
        >
          <q-item-section avatar>
            <q-icon :name="module.icon" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ module.title }}</q-item-label>
            <q-item-label v-if="!module.to" caption>Этап {{ module.stage }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref } from 'vue'
import modules from '@/modules/registry'

const drawerOpen = ref(false)
</script>
