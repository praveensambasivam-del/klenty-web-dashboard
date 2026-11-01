// Hourly timer: asks GitHub to start the dashboard refresh job.
// Why: GitHub's own schedule is best effort and often skips runs. Cloudflare cron triggers are punctual.
// Secret needed (Cloudflare > Worker > Settings > Variables and Secrets): GITHUB_TOKEN
//   = a fine-grained GitHub token for ONLY the klenty-web-dashboard repo with permission "Actions: Read and write".
const REPO = "praveensambasivam-del/klenty-web-dashboard";
const WORKFLOW = "refresh.yml";

async function startRefresh(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "klenty-dashboard-timer",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) throw new Error(`GitHub answered ${r.status}: ${await r.text()}`);
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(startRefresh(env));
  },
  // The web address does nothing except say hello, so nobody can trigger runs by visiting it.
  async fetch() {
    return new Response("Klenty dashboard timer. It starts a refresh every hour.", { status: 200 });
  },
};
