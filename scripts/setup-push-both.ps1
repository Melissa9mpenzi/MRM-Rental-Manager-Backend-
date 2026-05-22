# Push every commit to BOTH Melissa (origin) and you (nakungu-esther) with one `git push`.
# Run once per repo: .\scripts\setup-push-both.ps1

$ErrorActionPreference = "Stop"
$GitHubUser = "nakungu-esther"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot
$folderName = Split-Path $repoRoot -Leaf

$melissaUrl = (git remote get-url origin 2>$null)
if (-not $melissaUrl) {
    Write-Error "No origin remote. Clone from Melissa's repo first."
}
$myUrl = "https://github.com/$GitHubUser/$folderName.git"

# One remote "origin": fetch from Melissa, push to BOTH on every `git push origin`
git remote set-url origin $melissaUrl
git remote set-url --push origin $melissaUrl
git remote set-url --add --push origin $myUrl

# Drop duplicate remote if present (optional cleanup)
$remotes = git remote
if ($remotes -match "^mygithub$") {
    git remote remove mygithub
}

$branch = (git branch --show-current).Trim()
git branch --set-upstream-to="origin/$branch" $branch 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Branch '$branch' will track origin after first push."
}

Write-Host "Configured: git push -> Melissa + $GitHubUser" -ForegroundColor Green
Write-Host "  fetch:  $melissaUrl"
Write-Host "  push:   $melissaUrl"
Write-Host "  push:   $myUrl"
Write-Host ""
Write-Host "From now on, after commits run:  git push"
