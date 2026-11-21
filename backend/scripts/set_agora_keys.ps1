# Prompts for the Agora App ID and App Certificate (typing is hidden) and writes them into backend\.env.
# Nothing is printed except how many characters each value has. Press Enter to keep a value that is already set.
# Both values come from Agora Console -> your project (App ID, and the PRIMARY certificate). Each is 32 characters.
#
# Run from PowerShell:   powershell -NoProfile -ExecutionPolicy Bypass -File D:\hackthon\backend\scripts\set_agora_keys.ps1

$envPath = Join-Path $PSScriptRoot '..\.env' | Resolve-Path | Select-Object -ExpandProperty Path

function Read-Secret([string]$prompt) {
    $secure = Read-Host -Prompt $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim().Trim('"').Trim("'") }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Set-EnvLine([string]$text, [string]$name, [string]$value) {
    $pattern = "(?m)^$name=[^\r\n]*"
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) "$name=$value" }
    if ([regex]::IsMatch($text, $pattern)) { return [regex]::Replace($text, $pattern, $evaluator) }
    return $text.TrimEnd() + "`r`n$name=$value`r`n"
}

$text = [IO.File]::ReadAllText($envPath)

$appId = Read-Secret 'Agora App ID (32 characters)'
$cert  = Read-Secret 'Agora App Certificate (32 characters, the Primary one)'

foreach ($pair in @(@('App ID', $appId), @('App Certificate', $cert))) {
    if ($pair[1] -and $pair[1] -notmatch '^[0-9a-fA-F]{32}$') {
        Write-Host ("Warning: the {0} you typed is {1} characters or not hexadecimal; Agora values are normally 32 hex characters." -f $pair[0], $pair[1].Length) -ForegroundColor Yellow
    }
}

if ($appId) { $text = Set-EnvLine $text 'AGORA_APP_ID' $appId }
if ($cert)  { $text = Set-EnvLine $text 'AGORA_APP_CERTIFICATE' $cert }

[IO.File]::WriteAllText($envPath, $text, (New-Object System.Text.UTF8Encoding $false))

Write-Host ''
Write-Host "Saved to $envPath" -ForegroundColor Green
foreach ($name in 'AGORA_APP_ID', 'AGORA_APP_CERTIFICATE', 'MURF_API_KEY') {
    $m = [regex]::Match($text, "(?m)^$name=([^\r\n]*)")
    $v = if ($m.Success) { $m.Groups[1].Value.Trim() } else { '' }
    '{0,-22} {1}' -f $name, $(if ($v) { "set ($($v.Length) characters)" } else { 'STILL EMPTY' })
}
