export interface ArtifactPage {
  slug: string;
  title: string;
  description: string;
  file: string;
  tags: string[];
}

/**
 * Self-contained visual artifacts shipped into the build output (dist/artifacts/)
 * and shown in a same-origin iframe. `file` is the dist-relative path (relative
 * base is "./", so the app loads them next to index.html).
 */
export const artifactPages: ArtifactPage[] = [
  {
    slug: "interview-question-bank",
    title: "面试题库",
    description: "memx Agent 记忆系统面试题库，含来源指针与要点导航，可在此内嵌浏览。",
    file: "artifacts/interview-question-bank.html",
    tags: ["面试", "题库"],
  },
];

export function getArtifact(slug: string): ArtifactPage | null {
  return artifactPages.find((a) => a.slug === slug) ?? null;
}
