<script setup lang="ts">
// P4 阶段实现完整仪表盘（磁贴/分组/搜索/小组件）
</script>

<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="brand">Portal</div>
      <el-menu default-active="dashboard">
        <el-menu-item index="dashboard">首页</el-menu-item>
        <el-menu-item index="apps" disabled>应用</el-menu-item>
        <el-menu-item index="monitor" disabled>监控</el-menu-item>
        <el-menu-item index="settings" disabled>设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="P0 骨架占位页：仪表盘将在 P4 实现（磁贴/分组/搜索/小组件）"
      />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.aside {
  border-right: 1px solid #e2e8f0;
}
.brand {
  font-weight: 700;
  font-size: 18px;
  padding: 16px;
  color: #1e3a8a;
}
</style>
