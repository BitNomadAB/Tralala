// @ts-check
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import { createTypeScriptImportResolver } from "eslint-import-resolver-typescript";
import { importX } from "eslint-plugin-import-x";
import jsxA11y from "eslint-plugin-jsx-a11y-x";
import reactHooks from "eslint-plugin-react-hooks";
import { reactRefresh } from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * Every enabled rule is an error. A warning that never fails a build is a warning nobody reads,
 * so shared configs that ship a rule at `warn` are promoted here instead of rule by rule.
 *
 * @param {import("eslint").Linter.Config[]} configs
 * @returns {import("eslint").Linter.Config[]}
 */
function allErrors(configs) {
  /** @param {import("eslint").Linter.RuleEntry | undefined} entry */
  const promote = (entry) => {
    if (entry === "warn" || entry === 1) return "error";
    if (Array.isArray(entry) && (entry[0] === "warn" || entry[0] === 1)) {
      return ["error", ...entry.slice(1)];
    }
    return entry;
  };
  return configs.map((config) =>
    config.rules
      ? {
          ...config,
          rules: Object.fromEntries(
            Object.entries(config.rules).map(([name, entry]) => [name, promote(entry)]),
          ),
        }
      : config,
  );
}

export default allErrors(
  defineConfig(
    globalIgnores(["dist/", "coverage/", "playwright-report/", "test-results/", "e2e/.data/"]),
    {
      // A rule is configured here or nowhere: an inline `eslint-disable` has no effect and is
      // reported, which `--max-warnings 0` turns into a failure.
      linterOptions: {
        noInlineConfig: true,
      },
    },
    {
      files: ["**/*.{js,mjs,ts,tsx}"],
      extends: [
        js.configs.recommended,
        tseslint.configs.strictTypeChecked,
        tseslint.configs.stylisticTypeChecked,
        importX.flatConfigs.recommended,
        importX.flatConfigs.typescript,
      ],
      languageOptions: {
        parserOptions: {
          projectService: true,
          tsconfigRootDir: import.meta.dirname,
        },
      },
      settings: {
        "import-x/resolver-next": [createTypeScriptImportResolver({ project: "./tsconfig.json" })],
      },
      rules: {
        "import-x/order": [
          "error",
          {
            groups: ["builtin", "external", "internal", "parent", "sibling", "index"],
            pathGroups: [{ pattern: "@/**", group: "internal" }],
            "newlines-between": "never",
            alphabetize: { order: "asc", caseInsensitive: true },
          },
        ],
        "import-x/no-cycle": ["error", { ignoreExternal: true }],
        // Off: TypeScript already checks these five (typescript-eslint, "Performance troubleshooting").
        "import-x/named": "off",
        "import-x/namespace": "off",
        "import-x/default": "off",
        "import-x/no-named-as-default-member": "off",
        "import-x/no-unresolved": "off",
        // Option: a handler returning into a void slot, e.g. `onClick={() => setOpen(false)}`.
        "@typescript-eslint/no-confusing-void-expression": [
          "error",
          { ignoreVoidReturningFunctions: true },
        ],
        // Option: strictTypeChecked's settings plus allowNumber, which interpolates predictably.
        "@typescript-eslint/restrict-template-expressions": [
          "error",
          {
            allowAny: false,
            allowBoolean: false,
            allowNever: false,
            allowNullish: false,
            allowNumber: true,
            allowRegExp: false,
          },
        ],
        // Option: `const { omitted, ...rest } = value` is how a key is left out of a copy.
        "@typescript-eslint/no-unused-vars": ["error", { ignoreRestSiblings: true }],
        // On: under verbatimModuleSyntax `import { type A } from "m"` still loads "m" at runtime;
        // TypeScript itself requires the `type` marker, so consistent-type-imports stays off.
        "@typescript-eslint/no-import-type-side-effects": "error",
      },
    },
    {
      files: ["src/**/*.{ts,tsx}"],
      extends: [
        reactHooks.configs.flat["recommended-latest"],
        reactRefresh.configs.vite(),
        jsxA11y.configs.strict,
      ],
      languageOptions: {
        globals: globals.browser,
      },
      rules: {
        // Off: autoFocus is only used to move focus into what the user just opened (WAI-ARIA dialog).
        "jsx-a11y-x/no-autofocus": "off",
      },
    },
    {
      // No type information here: the JavaScript files are outside tsconfig.json, and the journeys
      // import Playwright, which scripts/run-playwright.mjs links in rather than installs.
      files: ["**/*.{js,mjs}", "e2e/**/*.ts", "playwright.config.ts"],
      extends: [tseslint.configs.disableTypeChecked],
      languageOptions: {
        globals: globals.node,
      },
    },
    // Last, so it wins: layout is Prettier's (`prettier --check` in `pnpm lint`), and this turns
    // off every rule that would argue with it. In this config that is only no-unexpected-multiline,
    // which guards against a missing semicolon that Prettier always inserts.
    eslintConfigPrettier,
  ),
);
