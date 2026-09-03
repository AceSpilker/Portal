<script setup lang="ts">
/**
 * 外观设置面板（M02-18/19/20；dev-plan P4.6，提前落地 P7.2 的外观部分）。
 *
 * 暗色模式（跟随系统/亮/暗）、主题色（预设+自定义）、壁纸（纯色/渐变/图片 URL +
 * 模糊与遮罩）。保存即全局生效（useTheme 监听 settingsStore）。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useSettingsStore } from '../stores/settings'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const saving = ref(false)

const darkMode = ref<'auto' | 'light' | 'dark'>('auto')
const themeColor = ref('#5b5ff1')
const wallpaperType = ref<'none' | 'solid' | 'gradient' | 'image'>('none')
const wallpaperValue = ref('')
const wallpaperBlur = ref(0)
const wallpaperMask = ref(35)

const PRESET_COLORS = ['#4f6ef7', '#5b5ff1', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']
const PRESET_GRADIENTS = [
  'linear-gradient(135deg, #4f6ef7 0%, #8b5cf6 50%, #06b6d4 100%)',
  'linear-gradient(135deg, #0f172a 0%, #334155 100%)',
  'linear-gradient(135deg, #f43f5e 0%, #f59e0b 100%)',
  'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
]

onMounted(async () => {
  await settingsStore.load()
  const map = settingsStore.map
  darkMode.value = (map['appearance.dark_mode'] as 'auto' | 'light' | 'dark') || 'auto'
  themeColor.value = (map['appearance.theme_color'] as string) || '#5b5ff1'
  wallpaperType.value = (map['appearance.wallpaper_type'] as typeof wallpaperType.value) || 'none'
  wallpaperValue.value = (map['appearance.wallpaper_value'] as string) || ''
  wallpaperBlur.value = (map['appearance.wallpaper_blur'] as number) ?? 0
  wallpaperMask.value = (map['appearance.wallpaper_mask'] as number) ?? 35
})

let saveTimer: number | undefined

/** 防抖保存：el-radio/label 双事件等短时间多次触发合并为一次写入与提示 */
function save(tip?: string) {
  window.clearTimeout(saveTimer)
  saving.value = true
  saveTimer = window.setTimeout(async () => {
    try {
      await settingsStore.save({
        'appearance.dark_mode': darkMode.value,
        'appearance.theme_color': themeColor.value,
        'appearance.wallpaper_type': wallpaperType.value,
        'appearance.wallpaper_value': wallpaperValue.value,
        'appearance.wallpaper_blur': wallpaperBlur.value,
        'appearance.wallpaper_mask': wallpaperMask.value,
      })
      if (tip) ElMessage.success(tip)
    } catch (e) {
      ElMessage.error((e as Error).message)
    } finally {
      saving.value = false
    }
  }, 400)
}

function setDark(v: 'auto' | 'light' | 'dark') {
  darkMode.value = v
  save(t('settings.appearanceSaved'))
}

function setColor(c: string) {
  themeColor.value = c
  save(t('settings.appearanceSaved'))
}

function setWallpaperType(v: typeof wallpaperType.value) {
  wallpaperType.value = v
  if (v === 'solid' && !wallpaperValue.value) wallpaperValue.value = '#dbe4ff'
  if (v === 'gradient' && !wallpaperValue.value) wallpaperValue.value = PRESET_GRADIENTS[0]
  save(t('settings.appearanceSaved'))
}

function setWallpaperValue(v: string) {
  wallpaperValue.value = v
  save()
}
</script>

<template>
  <div class="appearance-body">
    <!-- 暗色模式 -->
    <section>
      <h3>{{ t('settings.darkTitle') }}</h3>
      <el-radio-group :model-value="darkMode" @update:model-value="setDark(String($event) as typeof darkMode)">
        <el-radio-button value="auto">{{ t('settings.darkAuto') }}</el-radio-button>
        <el-radio-button value="light">{{ t('settings.darkLight') }}</el-radio-button>
        <el-radio-button value="dark">{{ t('settings.darkDark') }}</el-radio-button>
      </el-radio-group>
    </section>

    <!-- 主题色 -->
    <section>
      <h3>{{ t('settings.colorTitle') }}</h3>
      <div class="swatches">
        <button
          v-for="c in PRESET_COLORS"
          :key="c"
          type="button"
          class="swatch"
          :class="{ active: themeColor.toLowerCase() === c.toLowerCase() }"
          :style="{ background: c }"
          @click="setColor(c)"
        />
        <el-color-picker :model-value="themeColor" @change="setColor(String($event || themeColor))" />
      </div>
    </section>

    <!-- 壁纸 -->
    <section>
      <h3>{{ t('settings.wallpaperTitle') }}</h3>
      <el-radio-group
        :model-value="wallpaperType"
        @update:model-value="setWallpaperType(String($event) as typeof wallpaperType)"
      >
        <el-radio-button value="none">{{ t('settings.wpNone') }}</el-radio-button>
        <el-radio-button value="solid">{{ t('settings.wpSolid') }}</el-radio-button>
        <el-radio-button value="gradient">{{ t('settings.wpGradient') }}</el-radio-button>
        <el-radio-button value="image">{{ t('settings.wpImage') }}</el-radio-button>
      </el-radio-group>

      <div v-if="wallpaperType === 'solid'" class="wp-row">
        <el-color-picker :model-value="wallpaperValue" @change="setWallpaperValue(String($event || '#dbe4ff'))" />
      </div>
      <div v-else-if="wallpaperType === 'gradient'" class="wp-row">
        <button
          v-for="g in PRESET_GRADIENTS"
          :key="g"
          type="button"
          class="grad"
          :class="{ active: wallpaperValue === g }"
          :style="{ background: g }"
          @click="setWallpaperValue(g); save(t('settings.appearanceSaved'))"
        />
      </div>
      <div v-else-if="wallpaperType === 'image'" class="wp-row">
        <el-input
          :model-value="wallpaperValue"
          :placeholder="t('settings.wpUrlPh')"
          clearable
          @change="setWallpaperValue(String($event || '')); save(t('settings.appearanceSaved'))"
        />
      </div>

      <div v-if="wallpaperType !== 'none'" class="wp-row sliders">
        <span class="wp-label">{{ t('settings.wpBlur') }}</span>
        <el-slider
          v-model="wallpaperBlur"
          :min="0"
          :max="20"
          style="max-width: 220px"
          @change="save(t('settings.appearanceSaved'))"
        />
        <span class="wp-label">{{ t('settings.wpMask') }}</span>
        <el-slider
          v-model="wallpaperMask"
          :min="0"
          :max="90"
          style="max-width: 220px"
          @change="save(t('settings.appearanceSaved'))"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.appearance-body {
  display: flex;
  flex-direction: column;
  gap: 26px;
  max-width: 560px;
}
section h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.swatches {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.swatch {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
}
.swatch.active {
  border-color: var(--p-text);
  box-shadow: 0 0 0 2px var(--p-card), 0 0 0 3.5px var(--p-text);
}
.wp-row {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.grad {
  width: 92px;
  height: 34px;
  border-radius: 9px;
  border: 2px solid transparent;
  cursor: pointer;
}
.grad.active {
  border-color: var(--p-text);
  box-shadow: 0 0 0 2px var(--p-card), 0 0 0 3.5px var(--p-text);
}
.sliders .wp-label {
  font-size: 12.5px;
  color: var(--p-muted);
  margin-left: 8px;
}
.sliders .wp-label:first-child {
  margin-left: 0;
}
</style>
