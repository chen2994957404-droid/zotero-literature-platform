<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['team'])
const d = ref(null)
const error = ref('')

// ── 精读（2026-10-12：单篇、不回写 Zotero；排队在主力机上一篇一篇跑）──
const dr = ref(null)
const drBusy = ref(false)
const drError = ref('')
let timer = null
const STATE = { queued: '排队中', running: '精读中（一篇几分钟）', done: '完成', failed: '没做成' }

async function loadDeepread(id) {
  try {
    dr.value = await api.deepread(id)
  } catch (e) {
    drError.value = String(e.message || e)
  }
  clearTimeout(timer)
  const st = dr.value?.job?.state
  if (st === 'queued' || st === 'running') timer = setTimeout(() => refresh(id), 5000)
}

async function refresh(id) {
  if (id !== props.id) return
  const before = dr.value?.job?.state
  await loadDeepread(id)
  if (before !== dr.value?.job?.state && dr.value?.job?.state === 'done') d.value = await api.paper(id)
}

async function startDeepread() {
  if (!confirm(`要精读这篇吗？

${dr.value.plan.note}

会调用大模型、要花钱（每天的花费上限照样管着）。`)) return
  drBusy.value = true
  drError.value = ''
  try {
    await api.startDeepread(props.id)
    await loadDeepread(props.id)
  } catch (e) {
    drError.value = String(e.message || e)
  } finally {
    drBusy.value = false
  }
}
onUnmounted(() => clearTimeout(timer))

watch(() => props.id, async (id) => {
  d.value = null
  dr.value = null
  error.value = ''
  drError.value = ''
  clearTimeout(timer)
  if (!id) return
  try {
    d.value = await api.paper(id)
  } catch (e) {
    error.value = String(e.message || e)
  }
  loadDeepread(id)
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

      <div v-if="dr" class="deepread">
        <template v-if="dr.job && (dr.job.state === 'queued' || dr.job.state === 'running')">
          <span class="badge run">{{ STATE[dr.job.state] }}</span><span class="muted small">{{ dr.job.note }}</span>
        </template>
        <template v-else>
          <button v-if="dr.plan.can" class="go" :disabled="drBusy" @click="startDeepread">精读这篇</button>
          <span class="muted small">{{ dr.plan.note }}</span>
          <span v-if="dr.job && dr.job.state !== 'done'" class="badge bad">上次：{{ dr.job.note }}</span>
        </template>
        <span v-if="drError" class="error small">{{ drError }}</span>
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
.deepread { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; padding: 8px 10px; border: 1px dashed var(--line); border-radius: 8px; }
.go { padding: 5px 12px; border-radius: 6px; border: 1px solid var(--accent); background: var(--panel); color: var(--accent); cursor: pointer; white-space: nowrap; }
.go:disabled { opacity: .5; cursor: default; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 10px; }
.badge.run { background: var(--accent-soft); color: var(--accent); }
.badge.bad { background: transparent; color: var(--warn); border: 1px solid var(--warn); }
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
