# Check if the virtual environment directory exists, if not, create it
if (-Not (Test-Path -Path ".venv")) {
    python -m venv .venv
}

# Activate the virtual environment
& .\.venv\Scripts\Activate.ps1

# Get the interpreter path
$INTERPRETER_PATH = (Get-Command python).Source
Write-Output $INTERPRETER_PATH

# Loop through all tool directories (except _shims) and make the <Tool>.py executable and install the requirements
$toolDirectories = Get-ChildItem -Directory | Where-Object { $_.Name -ne "_shims" }

foreach ($TOOL in $toolDirectories) {
    $TOOL_PATH = Join-Path $TOOL.FullName "$($TOOL.Name).py"
    icacls $TOOL_PATH /grant Everyone:(X)
    
    # Install the requirements for the tool if they exist
    $requirementsPath = Join-Path $TOOL.FullName "requirements.txt"
    if (Test-Path $requirementsPath) {
        pip install -r $requirementsPath
    }
    
    # Add a shim for the tool in the "shims" directory
    $shimPath = Join-Path "_shims" $TOOL.Name
    $shimContent = @"
#!/bin/bash
$INTERPRETER_PATH $(Resolve-Path $TOOL_PATH) `$\@
"@
    Set-Content -Path $shimPath -Value $shimContent -NoNewline
    icacls $shimPath /grant Everyone:(X)
}

# Update the PATH environment variable
$pathUpdate = 'export PATH="$PATH:' + (Resolve-Path "_shims") + '"'
Add-Content -Path $PROFILE -Value $pathUpdate