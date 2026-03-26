<template>
  <el-config-provider>
    <el-container class="app-container">
      <el-header class="app-header">
        <div class="header-brand">
          <el-icon :size="22" color="#409EFF"><VideoCamera /></el-icon>
          <span class="brand-name">{{ config.siteName }}</span>
          <span class="brand-desc">{{ config.siteDescription }}</span>
        </div>
        <el-menu
          mode="horizontal"
          :router="true"
          :default-active="$route.path"
          background-color="#1a1a2e"
          text-color="#ccc"
          active-text-color="#409EFF"
          class="header-nav"
        >
          <el-menu-item index="/">
            <el-icon><Monitor /></el-icon>
            Video Wall
          </el-menu-item>
          <el-menu-item index="/messages">
            <el-icon><Bell /></el-icon>
            Messages
          </el-menu-item>
        </el-menu>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import config from './config.js'
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background: #0d0d1a;
  color: #eee;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  padding: 0 16px;
  height: 56px !important;
  flex-shrink: 0;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 32px;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  color: #409EFF;
}

.brand-desc {
  font-size: 12px;
  color: #888;
}

.header-nav {
  flex: 1;
  border-bottom: none !important;
}

.app-main {
  flex: 1;
  overflow: hidden;
  padding: 0;
}
</style>
