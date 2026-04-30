function normalizeBasePath(value) {
  if (!value || value === "/") {
    return "";
  }

  const withLeadingSlash = value.startsWith("/") ? value : `/${value}`;
  return withLeadingSlash.replace(/\/+$/, "");
}

const siteBasePath = normalizeBasePath(process.env.NEXT_PUBLIC_SITE_BASE_PATH);

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  ...(siteBasePath
    ? {
        basePath: siteBasePath,
        assetPrefix: siteBasePath,
      }
    : {}),
};

export default nextConfig;
