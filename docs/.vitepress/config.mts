import { defineConfig } from 'vitepress'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

// config 位于 docs/.vitepress/ 下，源码目录 docs/ 是其上一级
const here = path.dirname(fileURLToPath(import.meta.url))
const docsDir = path.resolve(here, '..')

// 自动收集 docs/*.md 生成侧边栏，与现有文档一一对应、无需手工维护
function mdSidebar() {
  const files = fs
    .readdirSync(docsDir, { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith('.md'))
    .map((e) => e.name)
    .sort()

  const label = (f) => f.replace(/\.md$/, '').replace(/^index$/, '文档索引')
  return files.map((f) => {
    const link = f === 'index.md' ? '/' : `/${f.replace(/\.md$/, '')}`
    return { text: label(f), link }
  })
}

export default defineConfig({
  title: 'memx · Agent 长期记忆系统',
  description: '面向 Agent 的长期记忆系统文档（能力、接口、治理、部署）',
  lang: 'zh-Hans',
  base: '/',
  // 构建产物目录，与 vercel.json 的 outputDirectory 保持一致
  outDir: path.resolve(here, 'dist'),
  // 默认 public 目录为 docs/public，大 HTML 会被原样带入 dist 根目录
  themeConfig: {
    nav: [
      { text: '文档', link: '/agent-memory-flow' },
      { text: '面试题库', link: '/interview-question-bank.html' },
    ],
    sidebar: mdSidebar(),
    outline: { label: '本页目录' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdated: { text: '最后更新' },
  },
  markdown: {
    lineNumbers: true,
  },
})
