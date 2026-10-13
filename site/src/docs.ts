// Docs are inlined at build time through the virtual module produced by
// vite.config.ts. The key is the docs-relative path without the .md extension,
// e.g. "api-reference" or "architecture/retrieval" (memx keeps a flat docs/
// directory plus an architecture/ subtree). Chinese docs come from docs/,
// English translations from docs/en/ under identical keys; any missing English
// doc falls back to the Chinese source.
import { docsByLang } from "virtual:memx-docs";

export type Lang = "zh" | "en";
export const LANGS: Lang[] = ["zh", "en"];

export interface DocSection {
  id: string;
  title: string;
  blurb: string;
  items: DocItem[];
}

export interface DocItem {
  slug: string;
  title: string;
  summary: string;
}

export interface DocCatalog {
  sections: DocSection[];
  index: Record<string, DocItem>;
}

function heading(raw: string): string {
  const m = raw.match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : "";
}

function summaryOf(raw: string): string {
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    return t.replace(/^[-*+]\s+/, "").slice(0, 140);
  }
  return "";
}

// Curated sections in reading order. Each `slugs` list names docs that belong
// to the section; any doc not referenced anywhere is auto-filed under a
// trailing "其他/Other" section so no document is ever dropped from the catalog.
const sectionDefs: {
  id: string;
  title: Record<Lang, string>;
  blurb: Record<Lang, string>;
  slugs: string[];
}[] = [
  {
    id: "top",
    title: { zh: "总览", en: "Overview" },
    blurb: {
      zh: "文档索引与阅读路径。",
      en: "Doc index and the recommended reading path.",
    },
    slugs: ["index"],
  },
  {
    id: "capability",
    title: { zh: "理解能力", en: "Understanding Memory" },
    blurb: {
      zh: "分层模型、能力边界与整体链路。",
      en: "The layered model, capability boundaries, and the end-to-end flow.",
    },
    slugs: ["agent-memory-flow", "capability-matrix"],
  },
  {
    id: "architecture",
    title: { zh: "架构详解", en: "Architecture Deep-Dive" },
    blurb: {
      zh: "组件、数据模型、记忆分类、固化、检索、运行时流程、决策与路线图。",
      en: "Components, data models, classification, consolidation, retrieval, runtime flows, decisions, and the roadmap.",
    },
    slugs: [
      "architecture/README",
      "architecture/system-context",
      "architecture/components",
      "architecture/data-models",
      "architecture/memory-classification",
      "architecture/consolidation",
      "architecture/retrieval",
      "architecture/runtime-flows",
      "architecture/architecture-diagrams",
      "architecture/decisions",
      "architecture/verification",
      "architecture/gaps-and-roadmap",
    ],
  },
  {
    id: "integrate",
    title: { zh: "接入接口", en: "Integration" },
    blurb: {
      zh: "完整使用指南、SDK / CLI 接入与典型示例手册。",
      en: "The full usage guide, SDK / CLI integration, and the examples cookbook.",
    },
    slugs: ["usage", "api-reference", "cli", "examples-cookbook"],
  },
  {
    id: "quality",
    title: { zh: "质量评估", en: "Quality & Evaluation" },
    blurb: {
      zh: "离线评测数据集、指标与发布门槛。",
      en: "Offline eval datasets, metrics, and release gates.",
    },
    slugs: ["evals"],
  },
  {
    id: "govern",
    title: { zh: "治理与部署", en: "Governance & Deployment" },
    blurb: {
      zh: "冲突与遗忘治理、配置调优、生产部署与存储 Schema。",
      en: "Conflict and forgetting governance, tuning, production deployment, and the storage schema.",
    },
    slugs: [
      "memory-governance",
      "configuration-reference",
      "production-deployment",
      "storage-schema",
    ],
  },
];

// Raw markdown per language; missing English docs fall back to Chinese.
const rawByLang: Record<Lang, Record<string, string>> = {
  zh: docsByLang.zh,
  en: { ...docsByLang.zh, ...docsByLang.en },
};

const catalogs: Record<Lang, DocCatalog> = {} as Record<Lang, DocCatalog>;

function buildCatalog(lang: Lang): DocCatalog {
  const index: Record<string, DocItem> = {};
  for (const key of Object.keys(rawByLang[lang]).sort()) {
    const raw = rawByLang[lang][key];
    index[key] = { slug: key, title: heading(raw) || key, summary: summaryOf(raw) };
  }

  const referenced = new Set(sectionDefs.flatMap((s) => s.slugs));
  const sections: DocSection[] = sectionDefs.map((def) => ({
    id: def.id,
    title: def.title[lang],
    blurb: def.blurb[lang],
    items: def.slugs.filter((s) => index[s]).map((s) => index[s]),
  }));

  // Auto-file any docs that were not explicitly listed, so the catalog is total.
  const leftovers = Object.keys(index).filter((k) => !referenced.has(k));
  if (leftovers.length > 0) {
    sections.push({
      id: "misc",
      title: lang === "zh" ? "其他" : "Other",
      blurb: lang === "zh" ? "未归入上述分组的文档。" : "Docs not covered by the groups above.",
      items: leftovers.map((k) => index[k]),
    });
  }

  return { sections, index };
}

/** Curated catalog for a language (built lazily, then cached). */
export function catalogFor(lang: Lang): DocCatalog {
  if (!catalogs[lang]) catalogs[lang] = buildCatalog(lang);
  return catalogs[lang];
}

// Default catalog kept for convenience (Chinese source of truth).
export const docCatalog: DocCatalog = catalogFor("zh");

/** Resolve a hash route "#/doc/<slug>" to its raw markdown in the given language. */
export function getDoc(slug: string, lang: Lang = "zh"): { raw: string; item: DocItem } | null {
  const catalog = catalogFor(lang);
  const item = catalog.index[slug];
  if (!item) return null;
  return { raw: rawByLang[lang][slug] ?? "", item };
}

/** Flatten slugs in reading order (section order, not alphabetical). */
export function orderedDocSlugs(): string[] {
  return docCatalog.sections.flatMap((s) => s.items.map((i) => i.slug));
}
