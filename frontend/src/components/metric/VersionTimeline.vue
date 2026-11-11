<template>
  <ol class="timeline">
    <li v-for="version in versions" :key="version.id" class="timeline-item">
      <div class="timeline-marker" :class="{ 'is-current': version.is_current }"></div>
      <div class="timeline-body">
        <div class="row-between">
          <div class="row">
            <span class="version-no">v{{ version.version_no }}</span>
            <span class="chip"><b>team</b>{{ version.team_name ?? '—' }}</span>
            <span v-if="version.is_current" class="badge active">当前</span>
            <span class="badge" :class="version.parse_status === 'ok' ? 'active' : 'deprecated'">
              {{ version.parse_status === 'ok' ? '解析通过' : '解析失败' }}
            </span>
          </div>
          <span class="faint small">{{ version.effective_from ?? version.created_at ?? '—' }}</span>
        </div>
        <div class="dsl-code mt-2">{{ version.dsl_text }}</div>
        <div class="mt-2">
          <TupleChips :tuple="version.tuple" />
        </div>
        <div class="mt-2">
          <span class="faint small">该版本依赖集合：</span>
          <span v-if="version.dependencies.length" class="row" style="display: inline-flex; gap: 6px; flex-wrap: wrap">
            <router-link
              v-for="dep in version.dependencies"
              :key="dep"
              class="chip dep-chip"
              :to="`/graph`"
            >→ {{ dep }}</router-link>
          </span>
          <span v-else class="hint small">无 using 依赖</span>
        </div>
        <p v-if="version.parse_error" class="error-notice mt-2">{{ version.parse_error }}</p>
        <div class="row-between mt-2">
          <span class="faint small">提交人 {{ version.created_by ?? '—' }}</span>
          <div class="row" style="gap: 10px">
            <button
              v-if="canWrite && !version.is_current"
              class="btn btn-sm"
              :disabled="activatingId === version.id"
              @click="$emit('activate', version)"
            >
              {{ activatingId === version.id ? '切换中…' : `切换为当前（回切 v${version.version_no}）` }}
            </button>
            <router-link class="small link" :to="`/metrics/${version.metric_id}/dsl?version=${version.id}`">
              在编辑器中打开 →
            </router-link>
          </div>
        </div>
      </div>
    </li>
  </ol>
</template>

<script setup lang="ts">
import type { MetricVersion } from '../../types/metric'
import TupleChips from './TupleChips.vue'

defineProps<{ versions: MetricVersion[]; canWrite: boolean; activatingId: number | null }>()
defineEmits<{ (event: 'activate', version: MetricVersion): void }>()
</script>

<style scoped>
.timeline { list-style: none; margin: 0; padding: 0; }
.timeline-item { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 14px; padding-bottom: 18px; position: relative; }
.timeline-item::before {
  content: ''; position: absolute; left: 8px; top: 16px; bottom: 0; width: 1px; background: var(--rule);
}
.timeline-item:last-child { padding-bottom: 0; }
.timeline-item:last-child::before { display: none; }
.timeline-marker {
  width: 9px; height: 9px; margin-top: 8px; margin-left: 4px;
  border: 1px solid var(--sage); background: var(--paper-raised); border-radius: 50%;
}
.timeline-marker.is-current { background: var(--vermilion); border-color: var(--vermilion); }
.timeline-body { border: 1px solid var(--rule); border-left: 3px solid var(--sage); background: var(--paper-raised); padding: 12px 14px; }
.version-no { font-family: var(--font-display); font-size: 18px; color: var(--ink-strong); }
.link { color: var(--vermilion-deep); text-decoration: underline; text-underline-offset: 3px; }
.dep-chip { text-decoration: none; }
</style>
