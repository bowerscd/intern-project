import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/ts/**/*.test.ts"],
    globals: true,
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
});
