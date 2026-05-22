# Push to Melissa AND nakungu-esther (same as: setup + git push)
& (Join-Path $PSScriptRoot "setup-push-both.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git push
