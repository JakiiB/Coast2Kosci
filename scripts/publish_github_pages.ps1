$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "publish_cloud.py"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
  & $pythonCmd.Source $scriptPath @args
  exit $LASTEXITCODE
}

$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
  & $pyCmd.Source -3 $scriptPath @args
  exit $LASTEXITCODE
}

throw "Python 3 is required to run scripts\publish_cloud.py."
