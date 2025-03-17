Write-Output "Installing blemli tools in $(Get-Location)"
$reply = Read-Host "Are you sure? (Y/N)"
if ($reply -match '^[Yy]$') {
    git clone blemli/tools
    Set-Location -Path ".\tools"
    & "./install.ps1"
}
