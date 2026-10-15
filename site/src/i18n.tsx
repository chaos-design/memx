import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { LANGS, type Lang } from "./docs";

const STORAGE_KEY = "memx-lang";

// UI chrome strings. Doc content itself is translated in docs/en/; this covers
// the site shell (sidebar, home, gallery, pagers, empty states).
const STRINGS = {
  zh: {
    brandSub: "文档与产物",
    navigate: "导航",
    home: "首页 / 总览",
    gallery: "产物画廊",
    artifacts: "产物 (Artifacts)",
    langLabel: "English",
    langTitle: "切换到 English",
    navOpen: "打开导航菜单",
    navClose: "关闭导航菜单",
    // Home
    homeCrumb: "memx · 在线文档中心",
    heroKicker: "Agent 长期记忆 · 分层存储",
    heroTitle: "memx 文档中心与产物可视化",
    heroBody:
      "这是 memx 仓库的在线站点：左侧导航联动右侧内容区，覆盖「理解能力 → 架构详解 → 接入接口 → 治理与部署」的完整文档路径，仓库 artifacts/ 下的产物以内嵌可视化页面呈现。站点在构建时把 docs/ 与 artifacts/ 一起打包，支持中英文切换，并经 Vercel 直接部署。",
    readDocs: "阅读文档中心",
    browseArtifacts: "浏览全部产物",
    cardDocsKicker: "文档",
    cardDocsTitle: "文档中心",
    cardDocsBody: (n: number) => `能力、架构、接入、治理与部署多层阅读路径，共 ${n} 篇文档。`,
    cardGalleryKicker: "产物",
    cardGalleryTitle: "产物画廊",
    cardGalleryBody: "面试题库等可视化产物，以同来源 iframe 内嵌呈现。",
    cardFlowKicker: "架构",
    cardFlowTitle: "Agent 记忆系统整体流程",
    cardFlowBody: "L0–L4 分层、写入 / 读取 / 演化链路。",
    cardInterviewKicker: "可视化",
    cardInterviewTitle: "memx 面试题库",
    cardInterviewBody: "面向讲解与演练的交互式题库。",
    artifactsSectionTitle: "产物 (Artifacts)",
    artifactsSectionBlurb: "来自仓库 artifacts/，以内嵌可视化页面呈现",
    // Gallery
    galleryCrumb: "产物画廊",
    galleryTitle: "产物画廊",
    galleryDesc: (code: ReactNode) => (
      <>
        仓库 <code>{code}</code> 下的可视化产物。每个产物在独立的全屏内嵌视图中展示（同来源
        iframe，相对路径加载），可在此直接切换。
      </>
    ),
    // DocView
    docCrumb: "文档",
    docNotFound: "未找到文档",
    docNotFoundBody: (slug: ReactNode) => (
      <>
        没有 slug 为 <code>{slug}</code> 的文档。
      </>
    ),
    backHome: "返回首页",
    tocTitle: "本页目录",
    pagerPrev: "← 上一篇",
    pagerNext: "下一篇 →",
    pagerHome: "首页",
    pagerGallery: "产物画廊",
    // ArtifactView
    artifactCrumb: "产物",
    artifactNotFound: "未找到产物",
    artifactNotFoundBody: (slug: ReactNode) => (
      <>
        没有 slug 为 <code>{slug}</code> 的产物。
      </>
    ),
    browseAll: "浏览全部产物",
    openNewWindow: "新窗口打开 ↗",
    fullscreen: "全屏沉浸 ⛶",
    escExit: "Esc 退出",
    exitImmersive: "退出 ⤢",
    immersiveSuffix: "（沉浸模式）",
    pagerPrevArtifact: "← 上一个产物",
    pagerBack: "← 返回",
    pagerNextArtifact: "下一个产物 →",
    pagerDocs: "文档中心 →",
    pagerDocsTitle: "memx 文档",
  },
  en: {
    brandSub: "Docs & Artifacts",
    navigate: "Navigate",
    home: "Home",
    gallery: "Artifact Gallery",
    artifacts: "Artifacts",
    langLabel: "中文",
    langTitle: "Switch to 中文",
    navOpen: "Open navigation menu",
    navClose: "Close navigation menu",
    homeCrumb: "memx · Online Docs",
    heroKicker: "Long-term memory for agents · Layered storage",
    heroTitle: "memx Documentation & Artifact Gallery",
    heroBody:
      "This is the online site for the memx repository: sidebar navigation drives the content pane, docs span understanding → architecture → integration → governance & deployment, and the artifacts under artifacts/ are embedded as visual pages. The site bundles docs/ and artifacts/ at build time, supports Chinese / English switching, and deploys via Vercel.",
    readDocs: "Read the docs",
    browseArtifacts: "Browse artifacts",
    cardDocsKicker: "Docs",
    cardDocsTitle: "Documentation",
    cardDocsBody: (n: number) =>
      `Reading paths for capabilities, architecture, integration, and governance — ${n} docs in total.`,
    cardGalleryKicker: "Artifacts",
    cardGalleryTitle: "Artifact Gallery",
    cardGalleryBody: "The interview bank and other visual artifacts, embedded via a same-origin iframe.",
    cardFlowKicker: "Architecture",
    cardFlowTitle: "Agent Memory End-to-End Flow",
    cardFlowBody: "L0–L4 layers plus the write / read / evolution pipelines.",
    cardInterviewKicker: "Visual",
    cardInterviewTitle: "memx Interview Bank",
    cardInterviewBody: "An interactive question bank for walkthroughs and practice.",
    artifactsSectionTitle: "Artifacts",
    artifactsSectionBlurb: "From the repo artifacts/, rendered as embedded visual pages",
    galleryCrumb: "Artifact Gallery",
    galleryTitle: "Artifact Gallery",
    galleryDesc: (code: ReactNode) => (
      <>
        Visual artifacts from the repo <code>{code}</code> directory. Each artifact opens in its own
        fullscreen embedded view (same-origin iframe, relative paths) and can be switched here.
      </>
    ),
    docCrumb: "Docs",
    docNotFound: "Doc not found",
    docNotFoundBody: (slug: ReactNode) => (
      <>
        No doc with slug <code>{slug}</code>.
      </>
    ),
    backHome: "Back to home",
    tocTitle: "On this page",
    pagerPrev: "← Previous",
    pagerNext: "Next →",
    pagerHome: "Home",
    pagerGallery: "Artifact Gallery",
    artifactCrumb: "Artifact",
    artifactNotFound: "Artifact not found",
    artifactNotFoundBody: (slug: ReactNode) => (
      <>
        No artifact with slug <code>{slug}</code>.
      </>
    ),
    browseAll: "Browse all artifacts",
    openNewWindow: "Open in new window ↗",
    fullscreen: "Fullscreen ⛶",
    escExit: "Esc to exit",
    exitImmersive: "Exit ⤢",
    immersiveSuffix: " (immersive)",
    pagerPrevArtifact: "← Previous artifact",
    pagerBack: "← Back",
    pagerNextArtifact: "Next artifact →",
    pagerDocs: "Documentation →",
    pagerDocsTitle: "memx Docs",
  },
} as const;

export type Strings = (typeof STRINGS)["zh"];

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Strings;
}

const LangContext = createContext<LangContextValue | null>(null);

function initialLang(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "zh") return saved;
  } catch {
    // localStorage unavailable (privacy mode etc.) — default below.
  }
  return "zh";
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  const setLang = (next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore persistence failures; the toggle still works for the session.
    }
  };

  // Keep <html lang> in sync for font shaping and accessibility.
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const value = useMemo<LangContextValue>(() => ({ lang, setLang, t: STRINGS[lang] as Strings }), [lang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used within LangProvider");
  return ctx;
}

/** Cycle helper used by the single toggle button. */
export function nextLang(lang: Lang): Lang {
  const i = LANGS.indexOf(lang);
  return LANGS[(i + 1) % LANGS.length];
}
