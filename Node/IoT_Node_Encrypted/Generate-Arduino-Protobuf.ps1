$ErrorActionPreference = 'Stop'

$generatedDir = Join-Path $PSScriptRoot 'src\generated'
$schema = Join-Path $generatedDir 'sensor.proto'
$descriptor = Join-Path $generatedDir 'sensor.pb'
$nanopbGenerator = (& python -c "import pathlib, nanopb; print(pathlib.Path(nanopb.__file__).parent / 'generator' / 'nanopb_generator.py')").Trim()

if (-not (Test-Path -LiteralPath $nanopbGenerator)) {
    throw "nanopb 0.4.9.1 generator not found at: $nanopbGenerator"
}

Push-Location $generatedDir
try {
    & protoc --proto_path=$generatedDir --descriptor_set_out=$descriptor --include_imports 'sensor.proto'
    if ($LASTEXITCODE -ne 0) { throw 'protoc failed.' }

    # Preserve source declaration order so battery_voltage remains directly
    # after timestamp in the generated C structs, while retaining wire tag 19
    # in Status_Message for backward compatibility.
    & python $nanopbGenerator -I $generatedDir -D $generatedDir -L quote -s sort_by_tag:false $descriptor
    if ($LASTEXITCODE -ne 0) { throw 'nanopb generation failed.' }

    $header = Join-Path $generatedDir 'sensor.pb.h'
    $content = Get-Content -LiteralPath $header -Raw
    $content = $content.Replace('#include "pb.h"', '#include "../third_party/nanopb/pb.h"')
    Set-Content -LiteralPath $header -Value $content -NoNewline
}
finally {
    if (Test-Path -LiteralPath $descriptor) {
        Remove-Item -LiteralPath $descriptor
    }
    Pop-Location
}

Write-Host 'Arduino nanopb files regenerated from src/generated/sensor.proto.'
