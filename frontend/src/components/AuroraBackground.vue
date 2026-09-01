<script setup lang="ts">
/** 极光背景：多枚模糊光斑缓慢漂移，用于认证类页面。 */
</script>

<template>
  <div class="aurora" aria-hidden="true">
    <div class="blob b1" />
    <div class="blob b2" />
    <div class="blob b3" />
    <div class="grid" />
  </div>
</template>

<style scoped>
.aurora {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: radial-gradient(1200px 800px at 70% -10%, #0e1730 0%, var(--p-bg, #070b14) 60%);
  z-index: -1;
}
.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(110px);
  opacity: 0.5;
  will-change: transform;
}
.b1 {
  width: 480px;
  height: 480px;
  left: -120px;
  top: -80px;
  background: #4f46e5;
  animation: drift1 22s ease-in-out infinite alternate;
}
.b2 {
  width: 420px;
  height: 420px;
  right: -100px;
  top: 10%;
  background: #7c3aed;
  animation: drift2 26s ease-in-out infinite alternate;
}
.b3 {
  width: 380px;
  height: 380px;
  left: 30%;
  bottom: -160px;
  background: #0ea5e9;
  opacity: 0.32;
  animation: drift3 30s ease-in-out infinite alternate;
}
.grid {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(800px 500px at 50% 40%, #000 0%, transparent 75%);
  -webkit-mask-image: radial-gradient(800px 500px at 50% 40%, #000 0%, transparent 75%);
}
@keyframes drift1 {
  to {
    transform: translate(120px, 80px) scale(1.15);
  }
}
@keyframes drift2 {
  to {
    transform: translate(-100px, 120px) scale(0.9);
  }
}
@keyframes drift3 {
  to {
    transform: translate(80px, -100px) scale(1.2);
  }
}
@media (prefers-reduced-motion: reduce) {
  .blob {
    animation: none;
  }
}
</style>
