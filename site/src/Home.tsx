import { artifactPages } from "./artifacts";
import { docCatalog } from "./docs";
import { ROUTES } from "./routes";

const accents = ["blue", "cyan", "green", "purple", "yellow", "red"] as const;

export function Home() {
  const sections = docCatalog.sections;
  const totalDocs = docCatalog.sections.reduce((n, s) => n + s.items.length, 0);

  return (
    <div className="content-inner">
      <div className="crumb">memx · 在线文档中心</div>

      <div className="hero">
        <div className="hero-kicker">Agent 长期记忆 · 分层存储</div>
        <h1>memx 文档中心与产物可视化</h1>
        <p>
          这是 memx 仓库的在线站点：左侧导航联动右侧内容区，覆盖「理解能力 →
          接入接口 → 治理与部署」的完整文档路径，仓库 <code>artifacts/</code>{" "}
          下的产物以内嵌可视化页面呈现。 站点在构建时把{" "}
          <code>docs/</code> 与 <code>artifacts/</code> 一起打包， GitHub Actions 与 Vercel
          两种部署路径可直接运行。
        </p>
        <div className="hero-actions">
          <a href={ROUTES.doc("index")} className="btn primary">
            阅读文档中心
          </a>
          <a href={ROUTES.gallery} className="btn">
            浏览全部产物
          </a>
        </div>
      </div>

      <div className="grid" style={{ marginBottom: 8 }}>
        <a href={ROUTES.doc("index")} className="card">
          <div className="card-accent" />
          <div className="card-kicker">文档</div>
          <div className="card-title">文档中心</div>
          <div className="card-body">
            能力、接入、治理与部署四层阅读路径，共 {totalDocs} 篇文档。
          </div>
        </a>
        <a href={ROUTES.gallery} className="card">
          <div className="card-accent cyan" />
          <div className="card-kicker">产物</div>
          <div className="card-title">产物画廊</div>
          <div className="card-body">面试题库等可视化产物，以同来源 iframe 内嵌呈现。</div>
        </a>
        <a href={ROUTES.doc("agent-memory-flow")} className="card">
          <div className="card-accent green" />
          <div className="card-kicker">架构</div>
          <div className="card-title">Agent 记忆系统整体流程</div>
          <div className="card-body">L0–L4 分层、写入 / 读取 / 演化链路。</div>
        </a>
        <a href={ROUTES.doc("capability-matrix")} className="card">
          <div className="card-accent purple" />
          <div className="card-kicker">能力</div>
          <div className="card-title">能力矩阵</div>
          <div className="card-body">能力边界、接口映射与典型使用场景。</div>
        </a>
      </div>

      {sections
        .filter((s) => s.id !== "top")
        .map((section, i) => (
          <div key={section.id}>
            <div className="section-head">
              <h2>{section.title}</h2>
              <p>{section.blurb}</p>
            </div>
            <div className="grid">
              {section.items.map((item, j) => (
                <a key={item.slug} href={ROUTES.doc(item.slug)} className="card">
                  <div className={`card-accent ${accents[(i + j) % accents.length]}`} />
                  <div className="card-kicker">{section.id}</div>
                  <div className="card-title">{item.title}</div>
                  {item.summary ? <div className="card-body">{item.summary}</div> : null}
                </a>
              ))}
            </div>
          </div>
        ))}

      <div className="section-head">
        <h2>产物 (Artifacts)</h2>
        <p>来自仓库 artifacts/，以内嵌可视化页面呈现</p>
      </div>
      <div className="grid">
        {artifactPages.map((a) => (
          <a key={a.slug} href={ROUTES.artifact(a.slug)} className="card">
            <div className="card-accent" />
            <div className="card-kicker">{a.tags.join(" · ") || "artifact"}</div>
            <div className="card-title">{a.title}</div>
            <div className="card-body">{a.description}</div>
          </a>
        ))}
      </div>
    </div>
  );
}
