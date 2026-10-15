<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from './api.js'
import PaperDetail from './components/PaperDetail.vue'

const f = reactive({ q: '', corr: '', author: '', team: '', topic: '', year_from: '', year_to: '', journal: '', has: [], abstract: false })
const HAS = [['pdf', '有正文'], ['si', '有 SI'], ['summary', '已精读']]
const teams = ref([])
const topics = ref([])
const topicNote = () => topics.value.find((t) => t.name === f.topic)?.note || ''
const meta = ref(null)
const rows = ref([])
const total = ref(null)
const loading = ref(false)
const error = ref('')
const picked = ref('')

async function run() {
  loading.value = true
  error.value = ''
  try {
    const r = await api.search(f)
    rows.value = r.rows
    total.value = r.total
    if (!r.rows.some((x) => x.id === picked.value)) picked.value = r.rows[0]?.id || ''
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(f, { q: '', corr: '', author: '', team: '', topic: '', year_from: '', year_to: '', journal: '', has: [], abstract: false })
  run()
}

function byTeam(label) {
  f.team = label
  run()
}

function byTopic(name) {
  f.topic = name
  run()
}

onMounted(async () => {
  try {
    ;[teams.value, meta.value, topics.value] = await Promise.all([api.teams(), api.meta(), api.topics()])
  } catch (e) {
    error.value = '连不上后台：' + (e.message || e)
  }
  run()
})
</script>

<template>
  <header class="top">
    <div class="brand">文献库</div>
    <form class="searchbar" @submit.prevent="run">
      <input v-model="f.q" placeholder="DOI、标题里的词、作者名、期刊名……（多个词都要命中）" autofocus />
      <label class="chk"><input type="checkbox" v-model="f.abstract" @change="run" />连摘要一起搜</label>
      <button class="primary" type="submit">检索</button>
    </form>
  </header>

  <div class="layout">
    <aside class="filters">
      <label>专题
        <select v-model="f.topic" @change="run">
          <option value="">全部</option>
          <option v-for="t in topics" :key="t.name" :value="t.name">{{ t.name }}（{{ t.n }}）</option>
        </select>
      </label>
      <p v-if="f.topic && topicNote()" class="muted small topicnote">{{ topicNote() }}</p>
      <p v-if="!topics.length" class="muted small topicnote">还没有专题。让 Claude Science「把用到的文献放进专题『综述：XXX』」，这里就会出现。</p>
      <label>通讯作者<input v-model="f.corr" placeholder="中文名或拼音" @keyup.enter="run" /></label>
      <label>任意作者<input v-model="f.author" placeholder="中文名或拼音" @keyup.enter="run" /></label>
      <label>团队
        <select v-model="f.team" @change="run">
          <option value="">全部</option>
          <option v-for="t in teams" :key="t.name" :value="t.label">{{ t.label }}（{{ t.n_main }}{{ t.n_coop ? '+' + t.n_coop : '' }}）</option>
        </select>
      </label>
      <div class="row">
        <label>年份从<input v-model="f.year_from" inputmode="numeric" placeholder="2015" @keyup.enter="run" /></label>
        <label>到<input v-model="f.year_to" inputmode="numeric" placeholder="2026" @keyup.enter="run" /></label>
      </div>
      <label>期刊名包含<input v-model="f.journal" placeholder="如 Macromolecules" @keyup.enter="run" /></label>
      <fieldset>
        <legend>手上有</legend>
        <label v-for="[k, n] in HAS" :key="k" class="chk"><input type="checkbox" :value="k" v-model="f.has" @change="run" />{{ n }}</label>
      </fieldset>
      <div class="row">
        <button class="primary" @click="run">应用筛选</button>
        <button @click="reset">清空</button>
      </div>
      <p v-if="meta" class="muted small">
        作者索引 {{ meta.n_indexed }} 篇 · 团队 {{ meta.n_teams }} 个
        <br />索引更新于 {{ (meta.index_built_at || '未建').replace('T', ' ') }}
      </p>
    </aside>

    <main class="results">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else class="muted small">
        <template v-if="loading">检索中……</template>
        <template v-else-if="total !== null">共 {{ total }} 篇{{ total > rows.length ? `，列前 ${rows.length}` : '' }}</template>
      </p>
      <ul>
        <li v-for="r in rows" :key="r.id" :class="{ on: r.id === picked }" @click="picked = r.id">
          <div class="title">{{ r.title || '（无标题）' }}</div>
          <div class="sub">
            <span>{{ r.year || '?' }}</span>
            <span>{{ r.journal }}</span>
            <span v-if="r.corr.length">通讯：{{ r.corr.join('、') }}</span>
          </div>
          <div class="tags">
            <span v-for="t in r.topics" :key="'tp' + t" class="tag topic" @click.stop="byTopic(t)">专题：{{ t }}</span>
            <span v-if="r.team" class="tag team" @click.stop="byTeam(r.team)">组：{{ r.team }}</span>
            <span v-for="c in r.coop" :key="c" class="tag">合作：{{ c }}</span>
            <span v-if="r.has.pdf" class="tag ok">正文</span>
            <span v-if="r.has.si" class="tag ok">SI</span>
            <span v-if="r.has.summary" class="tag ok">精读</span>
          </div>
        </li>
      </ul>
    </main>

    <PaperDetail :id="picked" @team="byTeam" @topic="byTopic" />
  </div>
</template>

<style scoped>
.top { display: flex; gap: 16px; align-items: center; padding: 12px 20px; background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 2; }
.brand { font-weight: 700; font-size: 18px; white-space: nowrap; }
.searchbar { display: flex; gap: 10px; align-items: center; flex: 1; }
.searchbar input[type=text], .searchbar > input { flex: 1; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
.layout { display: grid; grid-template-columns: 240px minmax(0, 1fr) minmax(0, 1.1fr); gap: 0; height: calc(100vh - 61px); }
.filters { padding: 16px; border-right: 1px solid var(--line); overflow: auto; display: flex; flex-direction: column; gap: 12px; }
.filters label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
.filters input, .filters select { padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
.filters fieldset { border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; display: flex; flex-direction: column; gap: 4px; }
.filters legend { font-size: 13px; color: var(--muted); }
.row { display: flex; gap: 8px; }
.row > label { flex: 1; min-width: 0; }
.chk { flex-direction: row !important; align-items: center; gap: 6px !important; color: var(--text) !important; font-size: 14px !important; white-space: nowrap; }
button { white-space: nowrap; padding: 7px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); cursor: pointer; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.results { overflow: auto; padding: 8px 16px; border-right: 1px solid var(--line); }
.results ul { list-style: none; margin: 0; padding: 0; }
.results li { padding: 10px 12px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
.results li:hover { background: var(--panel); }
.results li.on { background: var(--accent-soft); border-color: var(--accent); }
.title { font-weight: 600; line-height: 1.35; }
.sub { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--muted); font-size: 13px; margin-top: 3px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.tag { font-size: 12px; padding: 1px 7px; border-radius: 10px; border: 1px solid var(--line); color: var(--muted); }
.tag.ok { color: var(--ok); background: var(--ok-soft); border-color: transparent; }
.tag.team { color: var(--accent); border-color: var(--accent); cursor: pointer; }
.tag.topic { color: var(--warn); border-color: var(--warn); cursor: pointer; }
.topicnote { margin: -6px 0 0; white-space: pre-wrap; }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.error { color: #c0392b; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; height: auto; }
  .filters, .results { border-right: none; border-bottom: 1px solid var(--line); }
  .top { flex-wrap: wrap; }
}
</style>
