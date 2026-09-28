param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath,
    [string]$Language = "en-US"
)

$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)

if (-not (Test-Path $ImagePath)) {
    Write-Error "Image file not found: $ImagePath"
    exit 1
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function AwaitAction($asyncOp, $type) {
    $asTask = $asTaskGeneric.MakeGenericMethod($type)
    $netTask = $asTask.Invoke($null, @($asyncOp))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

try {
    $file = AwaitAction ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $stream = AwaitAction ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = AwaitAction ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = AwaitAction ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    $engine = $null
    if ($Language) {
        $langObj = [Windows.Globalization.Language]::new($Language)
        if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($langObj)) {
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($langObj)
        }
    }
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    }
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
    }

    if ($null -eq $engine) {
        Write-Error "No supported OCR language engine found on this Windows system."
        exit 1
    }

    $ocrResult = AwaitAction ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    $words = @()
    foreach ($l in $ocrResult.Lines) {
        $lines += $l.Text
        foreach ($w in $l.Words) {
            $words += @{
                Text = $w.Text
                X = [int]$w.BoundingRect.X
                Y = [int]$w.BoundingRect.Y
                Width = [int]$w.BoundingRect.Width
                Height = [int]$w.BoundingRect.Height
            }
        }
    }

    @{
        Success = $true
        Text = $ocrResult.Text
        Lines = $lines
        Words = $words
        WordCount = $words.Count
        Language = $Language
    } | ConvertTo-Json -Depth 3
} catch {
    @{
        Success = $false
        Error = $_.Exception.Message
        WordCount = 0
        Lines = @()
        Words = @()
    } | ConvertTo-Json -Depth 2
}
