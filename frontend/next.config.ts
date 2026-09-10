import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Emit .next/standalone — a self-contained server bundle with only the
   * node_modules it actually reaches.
   *
   * Required by deploy/Dockerfile.frontend: the runner stage copies
   * .next/standalone and runs `node server.js`, which keeps the runtime image
   * off `next` entirely. Without this the directory is never emitted and the
   * image build fails on COPY.
   *
   * Inert everywhere else — `next dev` ignores it, and Vercel ignores it in
   * favour of its own build output.
   */
  output: "standalone",
};

export default nextConfig;
