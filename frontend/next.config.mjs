/** The browser only talks to this origin. /api is proxied to the FastAPI service, so session
 cookies stay same-origin and no CORS is needed. The API's address comes from API_ORIGIN at
 start-up; nothing in the app names a host. */
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const apiOrigin = process.env.API_ORIGIN || "http://localhost:9596";
// A new id per build: the service worker is registered as /sw.js?v=<id>, so every phone notices
// a new version and offers "Reload".
const buildId = process.env.NEXT_PUBLIC_BUILD_ID || new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);

// Files are served through the app in production; in development they may come straight from
// MinIO on this machine.
const filesOrigin = process.env.FILES_ORIGIN || "http://localhost:9601";
const csp = [
  "default-src 'self'",
  // Next.js writes small inline scripts into each page; nothing is loaded from elsewhere.
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${filesOrigin}`,
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: here,
  poweredByHeader: false,
  devIndicators: false,
  generateBuildId: async () => buildId,
  env: { NEXT_PUBLIC_BUILD_ID: buildId },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
  async headers() {
    const security = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=(self)" },
    ];
    // Development reloads code with eval, which a strict policy would block.
    if (process.env.NODE_ENV === "production") security.push({ key: "Content-Security-Policy", value: csp });
    return [
      // The browser checks for a new service worker on every visit; never let a proxy keep an old
      // one, and let it control the whole app.
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      { source: "/manifest.webmanifest", headers: [{ key: "Cache-Control", value: "no-cache" }] },
      { source: "/(.*)", headers: security },
    ];
  },
};
export default nextConfig;
