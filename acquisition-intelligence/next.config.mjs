/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Serve the static public/hub.html landing page at a clean /hub URL.
    return [{ source: "/hub", destination: "/hub.html" }];
  },
};

export default nextConfig;
