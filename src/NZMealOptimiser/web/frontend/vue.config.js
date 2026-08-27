module.exports = {
  publicPath: '/static/vue/',
  lintOnSave: false,
  // Multi-page: index → /app (production dashboard), test → /test (sandbox copy).
  // The two trees are deliberately independent: src/ = production, src/test/ = sandbox.
  // Promote sandbox → production with tools/frontend/promote_test_to_app.ps1.
  pages: {
    index: { entry: 'src/main.js', template: 'public/index.html', filename: 'index.html', title: 'NZ Meal Cost Optimiser' },
    test: { entry: 'src/test-main.js', template: 'public/index.html', filename: 'test.html', title: 'Test Workspace · NZ Meal Cost Optimiser' },
  },
};
