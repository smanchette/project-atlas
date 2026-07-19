[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,
    [Parameter(Mandatory = $true)]
    [string]$OutputFile,
    [string]$FinalUrl = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
    [string]$EvidenceId = "orlando-$([guid]::NewGuid())",
    [ValidateSet(1, 2)]
    [int]$SchemaVersion = 1
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimeRoot = (Resolve-Path (Join-Path $repositoryRoot ".runtime")).Path
$resolvedInput = (Resolve-Path -LiteralPath $InputFile).Path
$inputItem = Get-Item -LiteralPath $resolvedInput -Force

if ($inputItem.PSIsContainer -or $inputItem.LinkType) {
    throw "browser_evidence_input_not_regular_file"
}
if ($inputItem.Directory.FullName -ne $runtimeRoot) {
    throw "browser_evidence_input_path_unapproved"
}
if ($inputItem.Name -notmatch '^browser-evidence-input-[A-Za-z0-9_-]{8,64}\.html$') {
    throw "browser_evidence_input_path_unapproved"
}

$inputSha256 = (Get-FileHash -LiteralPath $resolvedInput -Algorithm SHA256).Hash.ToLowerInvariant()
$temporaryOutputName = "browser-evidence-output-$([guid]::NewGuid()).json"
$temporaryOutput = Join-Path $runtimeRoot $temporaryOutputName
$containerInput = "/atlas-evidence-runtime/$($inputItem.Name)"
$containerOutput = "/atlas-evidence-runtime/$temporaryOutputName"
$volume = "${runtimeRoot}:/atlas-evidence-runtime:rw"
$dockerArguments = @(
    "compose", "run", "--rm", "--no-deps", "-T",
    "-v", $volume,
    "-e", "ATLAS_BROWSER_EVIDENCE_RUNTIME_DIR=/atlas-evidence-runtime",
    "backend", "python", "-m", "scripts.capture_manual_browser_evidence",
    "--input-file", $containerInput,
    "--expected-input-sha256", $inputSha256,
    "--output", $containerOutput,
    "--final-url", $FinalUrl,
    "--evidence-id", $EvidenceId,
    "--schema-version", "$SchemaVersion"
)

try {
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "browser_evidence_helper_failed"
    }
    if (-not (Test-Path -LiteralPath $temporaryOutput -PathType Leaf)) {
        throw "browser_evidence_output_missing"
    }
    $destination = [System.IO.Path]::GetFullPath($OutputFile)
    $destinationParent = Split-Path -Parent $destination
    if ($destinationParent) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }
    Move-Item -LiteralPath $temporaryOutput -Destination $destination -Force
}
finally {
    if (Test-Path -LiteralPath $resolvedInput) {
        Remove-Item -LiteralPath $resolvedInput -Force
    }
    if (Test-Path -LiteralPath $temporaryOutput) {
        Remove-Item -LiteralPath $temporaryOutput -Force
    }
}
