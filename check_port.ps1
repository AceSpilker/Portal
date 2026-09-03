Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  $pidToCheck = $_.OwningProcess
  $proc = Get-Process -Id $pidToCheck -ErrorAction SilentlyContinue
  $name = if ($proc) { $proc.ProcessName } else { "dead" }
  $path = if ($proc) { $proc.Path } else { "unknown" }
  Write-Output ("PID=" + $pidToCheck + " NAME=" + $name + " PATH=" + $path)
}
