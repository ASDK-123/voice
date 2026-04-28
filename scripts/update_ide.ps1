# Using a more direct URL format for Antigravity stable releases
$url = "https://update.antigravity.google/latest/win64/AntigravitySetup_1.18.3.exe"
$dest = "$env:USERPROFILE\Desktop\AntigravitySetup_1.18.3.exe"

Write-Host "Re-attempting download from new URL: $url"
try {
    # Ensure security protocol is TLS 1.2
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $dest -ErrorAction Stop
    Write-Host "Download successful! Location: $dest"
}
catch {
    Write-Host "Direct download failed. Trying alternative official mirror..."
    $altUrl = "https://dl.google.com/antigravity/1.18.3/AntigravitySetup_1.18.3.exe"
    try {
        Invoke-WebRequest -Uri $altUrl -OutFile $dest -ErrorAction Stop
        Write-Host "Download successful via mirror! Location: $dest"
    }
    catch {
        Write-Error "All download attempts failed. Please manually download from: https://antigravity.google"
    }
}
