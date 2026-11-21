$py312 = "C:\Users\2faze\AppData\Local\Python\pythoncore-3.12-64\python.exe"
$py313 = "C:\Users\2faze\AppData\Local\Python\pythoncore-3.13-64\python.exe"
$script = "C:\Users\2faze\OneDrive\Documents\NANDAN\projects\veritas-lite\veritas-lite\backend\tests\_check_py.py"

foreach ($py in @($py312, $py313)) {
    if (Test-Path $py) {
        Write-Host "Checking $py..."
        & $py $script 2>&1
    }
}
