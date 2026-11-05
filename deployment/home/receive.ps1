$ErrorActionPreference = 'Stop'
$command = $env:SSH_ORIGINAL_COMMAND
if ($command -notmatch '^deploy ([0-9a-f]{40})$') { exit 2 }
$release = $Matches[1]
$directory = 'C:\ProgramData\Ziper\incoming'
$archive = Join-Path $directory ($release + '.tgz')
if (Test-Path $archive) { exit 3 }
try {
  $file = [System.IO.File]::Open($archive, 'CreateNew', 'Write', 'None')
  try { [Console]::OpenStandardInput().CopyTo($file) } finally { $file.Dispose() }
  wsl.exe -d Ubuntu --exec python3 /opt/ziper/ci/receive.py $release
  exit $LASTEXITCODE
} finally {
  if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
}
