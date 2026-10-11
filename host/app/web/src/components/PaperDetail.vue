<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['team'])
const d = ref(null)
const error = ref('')

watch(() => props.id, async (id) => {
  d.value = null
  error.value = ''
  if (!id) return
  try {
    d.value = await api.paper(id)
  } catch (e) {
    error.value = String(e.message || e)
  }
}, { immediate: true })

// 单位按出现顺序编号，作者后面标上标号（论文抬头的样子）
const insts = computed(() => {
  const list = []
  for (const a of d.value?.authors || []) for (const i of a.inst || []) if (!list.includes(i)) list.push(i)
  return list
})
const instNo = (i) => insts.value.indexOf(i) + 1

const links = computed(() => {
  if (!d.value) return []
  const f = d.value.files
  const out = []
  if (f.summary) out.push(['summary', '正文精读'])
  if (f.summary_full) out.push(['summary_full', '全文精读（含 SI）'])
  if (f.si_summary) out.push(['si_summary', 'SI 精读'])
  if (f.pdf) out.push(['pdf', '正文 PDF'])
  if (f.si) out.push(['si', 'SI 原件'])
  return out
})
</script>

<template>
  <section class="detail">
    <p v-if="!id" class="muted">选一篇看详情</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="!d" class="muted">读取中……</p>
    <template v-else>
      <h2>{{ d.title }}</h2>
      <p class="sub">
        {{ d.year || '?' }} · {{ d.journal }}
        <template v-if="d.doi"> · <a :href="'https://doi.org/' + d.doi" target="_blank" rel="noopener">{{ d.doi }}</a></template>
      </p>

      <div class="actions">
        <a v-for="[k, n] in links" :key="k" class="btn" :href="api.file(d.id, k)" target="_blank" rel="noopener">{{ n }}</a>
        <span v-if="!links.length" class="muted small">本地还没有正文 / 精读</span>
      </div>

      <div v-if="d.team || d.coop.length" class="teams">
        <span v-if="d.team" class="tag team" @click="emit('team', d.team)">组：{{ d.team }}</span>
        <span v-for="c in d.coop" :key="c" class="tag team" @click="emit('team', c)">合作：{{ c }}</span>
      </div>

      <h3>作者 <span class="muted small">（✉ 通讯作者）</span></h3>
      <p v-if="!d.authors.length" class="muted small">没有作者数据（OpenAlex 没对上这篇）</p>
      <p class="authors">
        <span v-for="(a, k) in d.authors" :key="k" :class="{ corr: a.c }">
          {{ a.n }}<sup v-if="a.inst.length">{{ a.inst.map(instNo).join(',') }}</sup><span v-if="a.c">✉</span><template v-if="k < d.authors.length - 1">, </template>
        </span>
      </p>
      <ol class="insts">
        <li v-for="i in insts" :key="i">{{ i }}</li>
      </ol>

      <h3>摘要</h3>
      <p v-if="d.abstract" class="abstract">{{ d.abstract }}</p>
      <p v-else class="muted small">OpenAlex 没有这篇的摘要</p>

      <p class="muted small">证据库编号 {{ d.id }}{{ d.in_zotero ? ' · 也在 Zotero 里' : '' }}</p>
    </template>
  </section>
</template>

<style scoped>
.detail { overflow: auto; padding: 16px 20px; }
h2 { font-size: 18px; line-height: 1.35; margin: 0 0 6px; }
h3 { font-size: 14px; margin: 18px 0 6px; }
.sub { color: var(--muted); font-size: 13px; margin: 0; word-break: break-all; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 4px; }
.btn { padding: 6px 12px; border-radius: 6px; background: var(--accent); color: #fff; text-decoration: none; font-size: 14px; }
.teams { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tag { font-size: 12px; padding: 1px 7px; border-radius: 10px; border: 1px solid var(--accent); color: var(--accent); cursor: pointer; }
.authors { line-height: 1.7; margin: 0; }
.authors .corr { font-weight: 600; }
sup { font-size: 10px; color: var(--muted); margin-left: 1px; }
.insts { color: var(--muted); font-size: 13px; padding-left: 20px; margin: 6px 0 0; }
.abstract { line-height: 1.65; margin: 0; white-space: pre-wrap; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: #c0392b; }
</style>
