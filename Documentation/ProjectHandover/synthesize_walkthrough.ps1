param(
    [Parameter(Mandatory)][string]$WorkDirectory
)

$ErrorActionPreference = 'Stop'
$scenes = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'walkthrough.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$voice = New-Object -ComObject SAPI.SpVoice
$voice.Rate = -1
$index = 0
foreach ($scene in $scenes) {
    foreach ($step in $scene.steps) {
        $path = Join-Path $WorkDirectory ('voice_{0:00}.wav' -f $index)
        $stream = New-Object -ComObject SAPI.SpFileStream
        try {
            $stream.Open($path, 3, $false)
            $voice.AudioOutputStream = $stream
            [void]$voice.Speak([string]$step[1], 0)
        } finally {
            $stream.Close()
        }
        $index++
    }
}
Write-Output "Narrated $index cues"
