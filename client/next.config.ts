import type { NextConfig } from "next";

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  // standalone 模式：Docker 部署必须，生成独立的 server.js
  output: "standalone",
  devIndicators: {
    position: "bottom-right",
  },
  async rewrites() {
    return [
      // 所有后端路径统一代理
      {
        source: "/api/:path*",
        destination: `${BACKEND}/api/:path*`,
      },
      {
        source: "/schedules/:path*",
        destination: `${BACKEND}/schedules/:path*`,
      },
      {
        source: "/history/:path*",
        destination: `${BACKEND}/history/:path*`,
      },
      {
        source: "/artifacts/:path*",
        destination: `${BACKEND}/artifacts/:path*`,
      },
      {
        source: "/workspace/:path*",
        destination: `${BACKEND}/workspace/:path*`,
      },
      {
        source: "/tasks/:path*",
        destination: `${BACKEND}/tasks/:path*`,
      },
      {
        source: "/skills/:path*",
        destination: `${BACKEND}/skills/:path*`,
      },
      {
        source: "/knowledge/:path*",
        destination: `${BACKEND}/knowledge/:path*`,
      },
      {
        source: "/memory/:path*",
        destination: `${BACKEND}/memory/:path*`,
      },
      {
        source: "/approval/:path*",
        destination: `${BACKEND}/approval/:path*`,
      },
      {
        source: "/policy/:path*",
        destination: `${BACKEND}/policy/:path*`,
      },
      {
        source: "/cost/:path*",
        destination: `${BACKEND}/cost/:path*`,
      },
      {
        source: "/maintenance/:path*",
        destination: `${BACKEND}/maintenance/:path*`,
      },
      {
        source: "/chat/:path*",
        destination: `${BACKEND}/chat/:path*`,
      },
      {
        source: "/fs/:path*",
        destination: `${BACKEND}/fs/:path*`,
      },
    ];
  },
};

export default nextConfig;
