// Frontend linting.
//
// The Python half of this repo has been linted since it existed. The half that
// renders untrusted text into a browser had nothing, and that is where the
// stored XSS and the dead code both lived. eslint-plugin-html is what reaches
// the script block inside index.html without first splitting the file apart.
import html from "eslint-plugin-html";
import globals from "globals";

export default [
  {
    // Vendored and generated trees. Without this it lints the Python
    // virtualenv, which ships JavaScript of its own.
    ignores: [
      "node_modules/**",
      ".venv/**",
      "test-results/**",
      "playwright-report/**",
      "exports/**",
      "audio_recordings/**",
    ],
  },
  {
    files: ["**/*.html", "**/*.js", "**/*.mjs"],
    plugins: { html },
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...globals.browser, lucide: "readonly" },
    },
    rules: {
      // Correctness. These do not need to see the markup, so they work.
      "no-undef": "error",
      "eqeqeq": ["error", "smart"],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-unsafe-optional-chaining": "error",
      "no-promise-executor-return": "error",
      "no-unreachable-loop": "error",
      "no-constant-condition": "error",
      "no-dupe-keys": "error",
      "no-dupe-else-if": "error",
      "no-self-compare": "error",
      "no-template-curly-in-string": "error",
      "require-atomic-updates": "warn",
      "no-console": ["warn", { allow: ["warn", "error"] }],

      // Off, and this is a statement about the architecture rather than about
      // the rules. Every handler in this page is wired as onclick="fn()" in
      // markup, which ESLint does not parse, so every one of them reads as an
      // unused global. Turning these on produces 78 false positives and zero
      // findings.
      //
      // They become useful the day the JS moves out of index.html and binds
      // its handlers in code, which is the change atlas recommended. Until
      // then this file cannot answer "is this function dead", and `reaper` is
      // the tool that can.
      "no-implicit-globals": "off",
      "no-unused-vars": "off",
    },
  },
  {
    files: ["eslint.config.mjs", "playwright.config.ts", "e2e/**"],
    languageOptions: { sourceType: "module", globals: { ...globals.node } },
  },
];
