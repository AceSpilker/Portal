<script setup lang="ts">
/** 极光背景（亮色版）：柔和彩色光斑缓慢漂移，用于认证类页面。 */
</script>

<template>
  <div class="aurora" aria-hidden="true">
    <div class="blob b1" />
    <div class="blob b2" />
    <div class="blob b3" />
  </div>
</template>

<style scoped>
.aurora {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: linear-gradient(180deg, #f2f4fc 0%, #eef1f8 55%, #eef2f9 100%);
  z-index: -1;
}
.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.5;
  will-change: transform;
}
.b1 {
  width: 460px;
  height: 460px;
  left: -140px;
  top: -120px;
  background: rgba(99, 102, 241, 0.35);
  animation: drift1 22s ease-in-out infinite alternate;
}
.b2 {
  width: 420px;
  height: 420px;
  right: -120px;
  top: 6%;
  background: rgba(139, 92, 246, 0.28);
  animation: drift2 26s ease-in-out infinite alternate;
}
.b3 {
  width: 380px;
  height: 380px;
  left: 28%;
  bottom: -160px;
  background: rgba(34, 211, 238, 0.22);
  animation: drift3 30s ease-in-out infinite alternate;
}
@keyframes drift1 {
  to {
    transform: translate(120px, 80px) scale(1.15);
  }
}
@keyframes drift2 {
  to {
    transform: translate(-100px, 110px) scale(0.9);
  }
}
@keyframes drift3 {
  to {
    transform: translate(80px, -110px) scale(1.18);
  }
}
@media (prefers-reduced-motion: reduce) {
  .blob {
    animation: none;
  }
}
@media (max-width: 767px) {
  .blob {
    filter: blur(70px);
    opacity: 0.38;
  }
}
</style>
