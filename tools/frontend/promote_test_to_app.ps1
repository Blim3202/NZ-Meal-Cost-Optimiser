# Promotes the /test sandbox frontend (src/test/) over the production /app
# tree (src/). Run from anywhere; paths are resolved relative to this file.
#
#   powershell -File tools\frontend\promote_test_to_app.ps1
#
# After copying, review the diff of src/App.vue before committing.

$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot '..\..\src\NZMealOptimiser\web\frontend\src'
$src = [System.IO.Path]::GetFullPath($src)

if (-not (Test-Path (Join-Path $src 'test\TestApp.vue'))) {
    throw "Sandbox not found at $src\test - nothing to promote."
}

$items = @('views', 'components', 'composables', 'settings.js', 'styles.css',
           'resultUtils.js', 'unitOptions.js')
foreach ($item in $items) {
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $src "test\$item") -Destination $src
}

# App.vue is now byte-identical to TestApp.vue (no workspace subtitle),
# so just copy it directly.
Copy-Item -Force -LiteralPath (Join-Path $src 'test\TestApp.vue') -Destination (Join-Path $src 'App.vue')

Write-Host "Promoted src/test/* -> src/*. Now run: npm run lint && npm run build"
