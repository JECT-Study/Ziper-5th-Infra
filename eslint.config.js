import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "worker-configuration.d.ts", ".wrangler/**", "eslint.config.js"] },
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.ts"],
    languageOptions: { parserOptions: { projectService: true } },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/consistent-type-imports": "error"
    }
  }
);
