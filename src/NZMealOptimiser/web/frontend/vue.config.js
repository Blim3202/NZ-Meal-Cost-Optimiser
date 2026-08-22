const path = require('path');

module.exports = {
  publicPath: '/static/vue/',
  outputDir: path.resolve(__dirname, '../static/vue'),
  lintOnSave: false,
  // Multi-page: index → /app (standard dashboard), test → /test (dish builder).
  pages: {
    index: { entry: 'src/main.js', template: 'public/index.html', filename: 'index.html', title: 'NZ Meal Cost Optimiser' },
    test: { entry: 'src/test-main.js', template: 'public/index.html', filename: 'test.html', title: 'Dish Builder · NZ Meal Cost Optimiser' },
  },
};
