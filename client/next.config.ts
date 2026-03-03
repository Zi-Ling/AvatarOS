import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // reactCompiler: true, // Removed based on user feedback to reduce dev tool noise
  devIndicators: {
    appIsrStatus: false, // Hide static generation indicator
    buildActivity: false, // Hide build activity indicator
    buildActivityPosition: 'bottom-right',
  },
};

export default nextConfig;
