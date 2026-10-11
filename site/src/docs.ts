// Docs are inlined at build time through the virtual module produced by
// vite.config.ts. memx docs are flat under docs/, so a slug is the filename
// without the .md extension, e.g. "api-reference".
import { docs } from "virtual:memx-docs";

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

function summaryOf(raw: string): string {
  const lines = raw.split("\n").filter((l) => l.trim());
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    return trimmed.replace(/^[-*+]\s+/, "").slice(0, 140);
  }
  return "";
}

function heading(raw: string): string {
  const m = raw.match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : "";
}

// Section layout mirrors the reading path described in docs/index.md:
// 理解能力 → 接入接口 → 治理与部署
const sections: DocSection[] = [
  {
    id: "top",
    title: "总览",
    blurb: "文档索引与阅读路径。",
    items: [],
  },
  {
    id: "capability",
    title: "理解能力",
    blurb: "分层模型、能力边界与整体链路。",
    items: [],
  },
  {
    id: "integrate",
    title: "接入接口",
    blurb: "SDK / CLI 接入、典型示例手册。",
    items: [],
  },
  {
    id: "govern",
    title: "治理与部署",
    blurb: "冲突与遗忘治理、配置调优、生产部署与存储 Schema。",
    items: [],
  },
];

// Flat docs: pin each known page to a section; anything new falls back by name.
const slugSection: Record<string, string> = {
  index: "top",
  "agent-memory-flow": "capability",
  "capability-matrix": "capability",
  "api-reference": "integrate",
  cli: "integrate",
  "examples-cookbook": "integrate",
  "memory-governance": "govern",
  "configuration-reference": "govern",
  "production-deployment": "govern",
  "storage-schema": "govern",
};

const catalog: DocCatalog = {
  sections,
  index: {},
};

for (const key of Object.keys(docs).sort()) {
  const raw = docs[key];
  const title = heading(raw) || key;
  const item: DocItem = { slug: key, title, summary: summaryOf(raw) };
  catalog.index[key] = item;

  const sectionId = slugSection[key] ?? (key === "index" ? "top" : "capability");
  let section = sections.find((s) => s.id === sectionId);
  if (!section) {
    section = { id: sectionId, title: sectionId, blurb: "", items: [] };
    sections.push(section);
  }
  section.items.push(item);
}

// Keep the "top" (index) section first, stable.
catalog.sections = [
  ...catalog.sections.filter((s) => s.id === "top"),
  ...catalog.sections.filter((s) => s.id !== "top"),
];

export const docCatalog = catalog;

/** Resolve a hash route "#/doc/<slug>" to its raw markdown. */
export function getDoc(slug: string): { raw: string; item: DocItem } | null {
  const item = catalog.index[slug];
  if (!item) return null;
  return { raw: docs[slug] ?? "", item };
}

/** Flatten slugs in reading order (section order, not alphabetical). */
export function orderedDocSlugs(): string[] {
  return catalog.sections.flatMap((s) => s.items.map((i) => i.slug));
}
