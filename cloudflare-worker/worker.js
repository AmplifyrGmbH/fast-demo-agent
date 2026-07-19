export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const parts = url.pathname.replace(/^\//, "").split("/");
    const slug = parts[0];

    if (!slug) {
      return new Response("FastDemo — Amplifyr", {
        headers: { "Content-Type": "text/plain" }
      });
    }

    // Versions-Support: ?v=1 → v1, sonst latest
    const version = url.searchParams.get("v");
    const key = version
      ? `demos/${slug}/v${version}/index.html`
      : `demos/${slug}/latest/index.html`;

    const obj = await env.R2.get(key);
    if (!obj) {
      return new Response("Demo nicht gefunden", { status: 404 });
    }

    // Versionierte Keys cachen, latest immer fresh
    const cacheHeader = version
      ? "public, max-age=3600"
      : "no-cache, no-store, must-revalidate";

    return new Response(obj.body, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": cacheHeader,
      },
    });
  },
};
