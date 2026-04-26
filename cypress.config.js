const { defineConfig } = require("cypress");

module.exports = defineConfig({
  e2e: {
    // Base URL of the running frontend dev server
    baseUrl: "http://localhost:5173",

    setupNodeEvents(on, config) {
      // No custom node events needed
    },
  },
});
