$ErrorActionPreference = 'Stop'
$command = $env:SSH_ORIGINAL_COMMAND
if ($command -eq 'check') { Write-Output 'ZIPER_CI_RECEIVER_READY'; exit 0 }
if ($command -notmatch '^deploy ([0-9a-f]{40})$') { exit 2 }
$release = $Matches[1]
$directory = 'C:\ProgramData\Ziper\incoming'
$archive = Join-Path $directory ($release + '.tgz')
if (Test-Path $archive) { exit 3 }
try {
  $file = [System.IO.File]::Open($archive, 'CreateNew', 'Write', 'None')
  try {
    $stream = [Console]::OpenStandardInput()
    $buffer = New-Object byte[] 65536
    $total = 0L
    while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $total += $count
      if ($total -gt 2000000000) { throw 'Release exceeds size limit' }
      $file.Write($buffer, 0, $count)
    }
  } finally { $file.Dispose() }
  wsl.exe -d Ubuntu --exec python3 /opt/ziper/ci/receive.py $release
  exit $LASTEXITCODE
} finally {
  if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
}
