/** @type {import('next').NextConfig} */
const isNetlify = process.env.NETLIFY === "true" || process.env.NETLIFY_LOCAL === "true";

const nextConfig = {
  ...(isNetlify ? {} : { output: "standalone" })
};

module.exports = nextConfig;
