# Prompts for your API keys (typing is hidden) and writes them into backend\.env.
# Nothing is printed except how many characters each key has. Press Enter to keep a value that is already set.
#
# Run from PowerShell:   powershell -NoProfile -ExecutionPolicy Bypass -File D:\hackthon\backend\scripts\set_keys.ps1

$envPath = Join-Path $PSScriptRoot '..\.env' | Resolve-Path | Select-Object -ExpandProperty Path

function Read-Secret([string]$prompt) {
    $secure = Read-Host -Prompt $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim().Trim('"').Trim("'") }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Set-EnvLine([string]$text, [string]$name, [string]$value) {
    $pattern = "(?m)^$name=[^\r\n]*"
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) "$name=$value" }  # evaluator: keys may contain '$'
    if ([regex]::IsMatch($text, $pattern)) { return [regex]::Replace($text, $pattern, $evaluator) }
    return $text.TrimEnd() + "`r`n$name=$value`r`n"
}

$text = [IO.File]::ReadAllText($envPath)

$sarvam = Read-Secret 'Sarvam API key (used for speech AND as the fallback LLM key)'
$groq   = Read-Secret 'Groq API key (primary LLM)'

if ($sarvam) { $text = Set-EnvLine $text 'SARVAM_API_KEY' $sarvam; $text = Set-EnvLine $text 'LLM_FALLBACK_API_KEY' $sarvam }
if ($groq)   { $text = Set-EnvLine $text 'LLM_API_KEY' $groq }

# UTF-8 *without* a byte-order mark (a BOM breaks some tools)
[IO.File]::WriteAllText($envPath, $text, (New-Object System.Text.UTF8Encoding $false))

Write-Host ''
Write-Host "Saved to $envPath" -ForegroundColor Green
foreach ($name in 'SARVAM_API_KEY', 'LLM_API_KEY', 'LLM_FALLBACK_API_KEY') {
    $m = [regex]::Match($text, "(?m)^$name=([^\r\n]*)")
    $v = if ($m.Success) { $m.Groups[1].Value.Trim() } else { '' }
    '{0,-22} {1}' -f $name, $(if ($v) { "set ($($v.Length) characters)" } else { 'STILL EMPTY' })
}
