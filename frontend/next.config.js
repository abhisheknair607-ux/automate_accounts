/** @type {import('next').NextConfig} */
const isNetlify = process.env.NETLIFY === "true" || process.env.NETLIFY_LOCAL === "true";
const useStandaloneOutput = process.env.NEXT_OUTPUT_STANDALONE === "true";

const nextConfig = {
  ...(isNetlify || !useStandaloneOutput ? {} : { output: "standalone" })
};

module.exports = nextConfig;
